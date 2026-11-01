import * as cdk from "aws-cdk-lib";
import * as events from "aws-cdk-lib/aws-events";
import * as targets from "aws-cdk-lib/aws-events-targets";
import * as iam from "aws-cdk-lib/aws-iam";
import * as lambda from "aws-cdk-lib/aws-lambda";
import {
  DynamoEventSource,
  SqsEventSource,
} from "aws-cdk-lib/aws-lambda-event-sources";
import { Construct } from "constructs";
import { Auth } from "./auth";
import { Data } from "./data";
import { Stage, pyFunction } from "./shared";

export interface NotifyProps {
  readonly stage: Stage;
  readonly data: Data;
  readonly auth: Auth;
  /** Verified SES sending domain, e.g. "mail.jobtracker.app". */
  readonly sesSendingDomain: string;
  readonly prepModelId: string;
}

/**
 * Notifications and background jobs (tasks 9-12):
 *  - `notifier`: the scan-report SES email (invoked at the end of a scan)
 *  - `reminderSweeper`: runs every 15 minutes, groups due reminders per user
 *  - `prepPack`: generates interview prep packs from the DynamoDB stream
 */
export class Notify extends Construct {
  readonly notifier: lambda.Function;
  readonly reminderSweeper: lambda.Function;
  readonly prepPack: lambda.Function;

  constructor(scope: Construct, id: string, props: NotifyProps) {
    super(scope, id);

    const sesEnv = {
      TABLE_NAME: props.data.table.tableName,
      SES_FROM: `no-reply@${props.sesSendingDomain}`,
    };

    const sesPolicy = new iam.PolicyStatement({
      actions: ["ses:SendEmail"],
      resources: ["*"],
      conditions: {
        StringEquals: { "ses:FromAddress": `no-reply@${props.sesSendingDomain}` },
      },
    });

    this.notifier = pyFunction(this, "Notifier", props.stage, {
      handler: "api.notify.handler",
      description: "Scan report email (X new, Y changes, To do)",
      environment: sesEnv,
    });
    props.data.table.grantReadData(this.notifier);
    this.notifier.addToRolePolicy(sesPolicy);

    this.reminderSweeper = pyFunction(this, "ReminderSweeper", props.stage, {
      handler: "api.reminders.sweeper_handler",
      description: "Every 15 min: send grouped deadline reminders",
      environment: sesEnv,
    });
    props.data.table.grantReadWriteData(this.reminderSweeper);
    this.reminderSweeper.addToRolePolicy(sesPolicy);

    new events.Rule(this, "ReminderSchedule", {
      ruleName: `job-tracker-${props.stage}-reminders`,
      schedule: events.Schedule.rate(cdk.Duration.minutes(15)),
      targets: [new targets.LambdaFunction(this.reminderSweeper)],
    });

    // prep packs: DynamoDB stream -> prep queue -> prepPack Lambda
    this.prepPack = pyFunction(this, "PrepPack", props.stage, {
      handler: "agent.prep.handler.handler",
      description: "Generate interview prep packs",
      timeout: cdk.Duration.minutes(3),
      memorySize: 1024,
      reservedConcurrentExecutions: 5,
      environment: {
        TABLE_NAME: props.data.table.tableName,
        PREP_MODEL_ID: props.prepModelId,
      },
    });
    props.data.table.grantReadWriteData(this.prepPack);
    props.auth.appSecrets.grantRead(this.prepPack);
    this.prepPack.addToRolePolicy(
      new iam.PolicyStatement({
        actions: ["bedrock:InvokeModel"],
        resources: ["*"],
      }),
    );
    this.prepPack.addEventSource(
      new SqsEventSource(props.data.prepQueue, { batchSize: 1 }),
    );

    // a stream router filters status->Interview transitions onto the prep queue
    const streamRouter = pyFunction(this, "StreamRouter", props.stage, {
      handler: "agent.prep.router.handler",
      description: "Route furthest-stage->Interview changes to the prep queue",
      environment: {
        TABLE_NAME: props.data.table.tableName,
        PREP_QUEUE_URL: props.data.prepQueue.queueUrl,
      },
    });
    props.data.prepQueue.grantSendMessages(streamRouter);
    streamRouter.addEventSource(
      new DynamoEventSource(props.data.table, {
        startingPosition: lambda.StartingPosition.LATEST,
        batchSize: 10,
        retryAttempts: 3,
        bisectBatchOnError: true,
      }),
    );
  }
}
