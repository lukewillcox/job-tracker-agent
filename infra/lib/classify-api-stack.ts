import * as cdk from "aws-cdk-lib";
import {
  CorsHttpMethod,
  HttpApi,
  HttpMethod,
} from "aws-cdk-lib/aws-apigatewayv2";
import { HttpLambdaIntegration } from "aws-cdk-lib/aws-apigatewayv2-integrations";
import * as dynamodb from "aws-cdk-lib/aws-dynamodb";
import * as iam from "aws-cdk-lib/aws-iam";
import { Construct } from "constructs";
import { Stage, pyFunction } from "./shared";

export interface ClassifyApiStackProps extends cdk.StackProps {
  readonly stage: Stage;
  readonly classifierModelId: string;
  /** Verified SES sender + the host's address for the 50%-of-cap alert. */
  readonly sesFromAddress: string;
  readonly adminAlertEmail: string;
}

/**
 * The SHARED classifier API (Milestone 5): a public HTTPS endpoint that
 * classifies emails on the host's Bedrock credits, authenticated by per-user
 * invite codes with daily caps.
 *
 * Deliberately isolated from the single-user JobTracker stack:
 *  - its own DynamoDB table (JobTrackerCodes), nothing else
 *  - Bedrock InvokeModel + that one table are the ONLY permissions
 *  - no access to the JobTracker application table or the KMS token key
 * so a leaked invite code can never reach application or token data.
 */
export class ClassifyApiStack extends cdk.Stack {
  readonly httpApi: HttpApi;
  readonly codesTable: dynamodb.Table;

  constructor(scope: Construct, id: string, props: ClassifyApiStackProps) {
    super(scope, id, props);

    this.codesTable = new dynamodb.Table(this, "CodesTable", {
      tableName: `JobTrackerCodes-${props.stage}`,
      partitionKey: { name: "PK", type: dynamodb.AttributeType.STRING },
      sortKey: { name: "SK", type: dynamodb.AttributeType.STRING },
      billingMode: dynamodb.BillingMode.PAY_PER_REQUEST,
      pointInTimeRecoverySpecification: { pointInTimeRecoveryEnabled: true },
      timeToLiveAttribute: "ttl", // daily usage rows expire
      removalPolicy:
        props.stage === "prod" ? cdk.RemovalPolicy.RETAIN : cdk.RemovalPolicy.DESTROY,
    });

    const handler = pyFunction(this, "ClassifyApi", props.stage, {
      handler: "classifyapi.handler.handler",
      description: "Shared classifier API (invite-code auth, daily caps)",
      timeout: cdk.Duration.seconds(60), // a batch of up to 25 Bedrock calls
      memorySize: 1024,
      environment: {
        CODES_TABLE: this.codesTable.tableName,
        CLASSIFIER_MODEL_ID: props.classifierModelId,
        SES_FROM: props.sesFromAddress,
        ADMIN_ALERT_EMAIL: props.adminAlertEmail,
      },
    });

    // least privilege: the codes table, Bedrock InvokeModel, and SES send from
    // the one verified identity (for the 50%-of-cap alert only).
    this.codesTable.grantReadWriteData(handler);
    handler.addToRolePolicy(
      new iam.PolicyStatement({
        actions: ["bedrock:InvokeModel"],
        resources: ["*"], // scope to the eu-north-1 Claude profile ARN at deploy
      }),
    );
    handler.addToRolePolicy(
      new iam.PolicyStatement({
        actions: ["ses:SendEmail"],
        resources: [
          cdk.Stack.of(this).formatArn({
            service: "ses",
            resource: "identity",
            resourceName: props.sesFromAddress,
          }),
        ],
        conditions: { StringEquals: { "ses:FromAddress": props.sesFromAddress } },
      }),
    );

    this.httpApi = new HttpApi(this, "HttpApi", {
      apiName: `job-tracker-classify-${props.stage}`,
      corsPreflight: {
        allowOrigins: ["*"], // called by the local CLI, not a browser
        allowMethods: [CorsHttpMethod.POST, CorsHttpMethod.GET],
        allowHeaders: ["content-type", "authorization"],
      },
    });
    const integration = new HttpLambdaIntegration("Integration", handler);
    this.httpApi.addRoutes({
      path: "/classify",
      methods: [HttpMethod.POST],
      integration,
    });
    this.httpApi.addRoutes({
      path: "/health",
      methods: [HttpMethod.GET],
      integration,
    });
    // authenticated usage summary (the friend's "beer tab")
    this.httpApi.addRoutes({
      path: "/me",
      methods: [HttpMethod.GET],
      integration,
    });

    new cdk.CfnOutput(this, "ClassifyApiUrl", { value: this.httpApi.apiEndpoint });
  }
}
