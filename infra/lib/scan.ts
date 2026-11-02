import * as cdk from "aws-cdk-lib";
import * as iam from "aws-cdk-lib/aws-iam";
import * as lambda from "aws-cdk-lib/aws-lambda";
import { SqsEventSource } from "aws-cdk-lib/aws-lambda-event-sources";
import * as sfn from "aws-cdk-lib/aws-stepfunctions";
import * as tasks from "aws-cdk-lib/aws-stepfunctions-tasks";
import { Construct } from "constructs";
import { Auth } from "./auth";
import { Data } from "./data";
import { Notify } from "./notify";
import { Stage, pyFunction } from "./shared";

export interface ScanProps {
  readonly stage: Stage;
  readonly data: Data;
  readonly auth: Auth;
  readonly notify: Notify;
  /** Bedrock model ids from configuration (tech.md). */
  readonly classifierModelId: string;
  readonly prepModelId: string;
  /** Microsoft app config for the token-refresh in ingest/excel. */
  readonly msClientId: string;
  readonly msAuthority: string;
}

/**
 * The scan pipeline (task 9): a Step Functions workflow orchestrating one scan
 * for one user, a `start_scan` Lambda driven by the SQS scan queue, and the
 * per-user EventBridge Scheduler plumbing (the schedules themselves are created
 * at runtime by the API via the scheduler role granted here).
 */
export class Scan extends Construct {
  readonly workflow: sfn.StateMachine;
  readonly startScan: lambda.Function;
  readonly schedulerRole: iam.Role;

  constructor(scope: Construct, id: string, props: ScanProps) {
    super(scope, id);

    const env = {
      TABLE_NAME: props.data.table.tableName,
      TOKEN_KEY_ARN: props.data.tokenKey.keyArn,
      APP_SECRETS_ARN: props.auth.appSecrets.secretArn,
      CLASSIFIER_MODEL_ID: props.classifierModelId,
      PREP_MODEL_ID: props.prepModelId,
      // for the token refresh in ingest/excel (no redirect uri needed)
      MS_CLIENT_ID: props.msClientId,
      MS_AUTHORITY: props.msAuthority,
      // claim-check scratch bucket (ingest -> classify message hand-off)
      SCRATCH_BUCKET: props.data.scratchBucket.bucketName,
    };

    // --- pipeline Lambdas -------------------------------------------------
    const ingest = pyFunction(this, "Ingest", props.stage, {
      handler: "agent.ingest.handler.handler",
      description: "Graph delta sync + prefilter",
      timeout: cdk.Duration.minutes(5),
      memorySize: 1024,
      environment: env,
    });
    const classify = pyFunction(this, "Classify", props.stage, {
      handler: "agent.classify.handler.handler",
      description: "Bedrock classification + schema validation",
      timeout: cdk.Duration.minutes(2),
      memorySize: 1024,
      // bound Bedrock concurrency so many users don't exhaust quota at once
      reservedConcurrentExecutions: 20,
      environment: env,
    });
    const matchApply = pyFunction(this, "MatchApply", props.stage, {
      handler: "agent.match.handler.handler",
      description: "Match emails to applications + status state machine",
      timeout: cdk.Duration.minutes(2),
      environment: env,
    });
    const excelExport = pyFunction(this, "ExcelExport", props.stage, {
      handler: "excel.handler.handler",
      description: "Write the Excel tracker to OneDrive",
      timeout: cdk.Duration.minutes(2),
      memorySize: 1024,
      environment: env,
    });

    for (const fn of [ingest, classify, matchApply, excelExport]) {
      props.data.table.grantReadWriteData(fn);
    }
    // claim-check: ingest writes the message shortlist, classify reads it
    props.data.scratchBucket.grantWrite(ingest);
    props.data.scratchBucket.grantRead(classify);
    // Token-handling functions decrypt the stored refresh token AND re-encrypt
    // the rotated one that Microsoft returns, so they need encrypt + decrypt.
    props.data.tokenKey.grantEncryptDecrypt(ingest);
    props.data.tokenKey.grantEncryptDecrypt(excelExport);
    props.auth.appSecrets.grantRead(ingest);
    props.auth.appSecrets.grantRead(excelExport);
    classify.addToRolePolicy(
      new iam.PolicyStatement({
        actions: ["bedrock:InvokeModel"],
        resources: ["*"], // scope to eu-north-1 model/inference-profile ARNs at deploy time
      }),
    );

    // --- Step Functions workflow -----------------------------------------
    const ingestTask = new tasks.LambdaInvoke(this, "IngestTask", {
      lambdaFunction: ingest,
      outputPath: "$.Payload",
    }).addRetry({ errors: ["States.ALL"], maxAttempts: 3, backoffRate: 2 });

    // Iterate over the small list of S3 keys (claim-check); each classify
    // invocation reads its one message body from the scratch bucket. itemSelector
    // builds the per-item payload {key, user_id, scan_id} the Lambda expects.
    const classifyMap = new sfn.Map(this, "ClassifyMap", {
      itemsPath: "$.message_keys",
      maxConcurrency: 5, // bounded fan-out to protect Bedrock
      resultPath: "$.classified",
      itemSelector: {
        "key.$": "$$.Map.Item.Value",
        "user_id.$": "$.user_id",
        "scan_id.$": "$.scan_id",
      },
    });
    classifyMap.itemProcessor(
      new tasks.LambdaInvoke(this, "ClassifyTask", {
        lambdaFunction: classify,
        outputPath: "$.Payload",
      }).addRetry({ errors: ["States.ALL"], maxAttempts: 3, backoffRate: 2 }),
    );

    const matchTask = new tasks.LambdaInvoke(this, "MatchTask", {
      lambdaFunction: matchApply,
      outputPath: "$.Payload",
    });
    const excelTask = new tasks.LambdaInvoke(this, "ExcelTask", {
      lambdaFunction: excelExport,
      outputPath: "$.Payload",
    });
    const notifyTask = new tasks.LambdaInvoke(this, "NotifyTask", {
      lambdaFunction: props.notify.notifier,
      outputPath: "$.Payload",
    });

    // Release the per-user scan lock on success AND on failure, so a scan that
    // errors part-way doesn't leave the user locked until the TTL expires.
    const releaseLock = pyFunction(this, "ReleaseLock", props.stage, {
      handler: "agent.release_lock.handler",
      description: "Release the per-user scan lock (terminal step)",
      environment: env,
    });
    props.data.table.grantReadWriteData(releaseLock);

    const releaseOnSuccess = new tasks.LambdaInvoke(this, "ReleaseLockSuccess", {
      lambdaFunction: releaseLock,
      outputPath: "$.Payload",
    });
    const releaseOnFailure = new tasks.LambdaInvoke(this, "ReleaseLockFailure", {
      lambdaFunction: releaseLock,
      // preserve the error: wrap it so release_lock can still find user_id
      payload: sfn.TaskInput.fromObject({
        "user_id.$": "$$.Execution.Input.user_id",
        "error.$": "$",
      }),
    }).next(new sfn.Fail(this, "ScanFailed", { cause: "scan pipeline failed" }));

    const pipeline = ingestTask
      .next(classifyMap)
      .next(matchTask)
      .next(excelTask)
      .next(notifyTask)
      .next(releaseOnSuccess);

    // any failure in the pipeline routes to release-then-fail
    for (const step of [ingestTask, classifyMap, matchTask, excelTask, notifyTask]) {
      step.addCatch(releaseOnFailure, { resultPath: "$.errorInfo" });
    }

    const definition = pipeline;

    this.workflow = new sfn.StateMachine(this, "ScanWorkflow", {
      stateMachineName: `job-tracker-${props.stage}-scan`,
      definitionBody: sfn.DefinitionBody.fromChainable(definition),
      timeout: cdk.Duration.minutes(15),
      tracingEnabled: true,
    });

    // --- start_scan: SQS -> start the workflow (per-user lock in code) ----
    this.startScan = pyFunction(this, "StartScan", props.stage, {
      handler: "agent.start_scan.handler",
      description: "Consume the scan queue and start one workflow per user",
      // cap concurrency so a thundering herd of schedules is smoothed
      reservedConcurrentExecutions: 10,
      environment: { ...env, SCAN_WORKFLOW_ARN: this.workflow.stateMachineArn },
    });
    props.data.table.grantReadWriteData(this.startScan);
    this.workflow.grantStartExecution(this.startScan);
    this.startScan.addEventSource(
      new SqsEventSource(props.data.scanQueue, { batchSize: 1 }),
    );

    // --- EventBridge Scheduler role (schedules created at runtime) --------
    this.schedulerRole = new iam.Role(this, "SchedulerRole", {
      assumedBy: new iam.ServicePrincipal("scheduler.amazonaws.com"),
      description: "Lets per-user EventBridge schedules enqueue scans",
    });
    props.data.scanQueue.grantSendMessages(this.schedulerRole);
  }
}
