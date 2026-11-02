import * as cdk from "aws-cdk-lib";
import {
  CorsHttpMethod,
  HttpApi,
  HttpMethod,
} from "aws-cdk-lib/aws-apigatewayv2";
import { HttpLambdaIntegration } from "aws-cdk-lib/aws-apigatewayv2-integrations";
import * as lambda from "aws-cdk-lib/aws-lambda";
import { Construct } from "constructs";
import { Auth } from "./auth";
import { Data } from "./data";
import { Stage, pyFunction } from "./shared";

export interface ApiProps {
  readonly stage: Stage;
  readonly data: Data;
  readonly auth: Auth;
  /** Allowed browser origin for the web app (CORS + cookie). */
  readonly webOrigin: string;
  /** Microsoft Entra app (client) id. */
  readonly msClientId: string;
  /** Sign-in authority; "common" accepts any tenant + personal accounts. */
  readonly msAuthority: string;
}

/**
 * HTTP API + the api Lambda (design.md "API"). A single handler serves all
 * routes via a catch-all; it reads the session cookie, enforces tenant
 * isolation and dispatches internally. "Scan now" enqueues to the scan queue.
 */
export class Api extends Construct {
  readonly httpApi: HttpApi;
  readonly handler: lambda.Function;

  constructor(scope: Construct, id: string, props: ApiProps) {
    super(scope, id);

    this.handler = pyFunction(this, "Handler", props.stage, {
      handler: "api.app.handler",
      description: "HTTP API handler (auth, applications, analytics, settings, export)",
      timeout: cdk.Duration.seconds(29), // under the API Gateway 30s limit
      memorySize: 1024,
      environment: {
        TABLE_NAME: props.data.table.tableName,
        TOKEN_KEY_ARN: props.data.tokenKey.keyArn,
        SCAN_QUEUE_URL: props.data.scanQueue.queueUrl,
        APP_SECRETS_ARN: props.auth.appSecrets.secretArn,
        WEB_ORIGIN: props.webOrigin,
      },
    });

    // least privilege: table RW, token decrypt (auth), secrets read, enqueue scan
    props.data.table.grantReadWriteData(this.handler);
    props.data.tokenKey.grantEncryptDecrypt(this.handler);
    props.auth.appSecrets.grantRead(this.handler);
    props.data.scanQueue.grantSendMessages(this.handler);

    this.httpApi = new HttpApi(this, "HttpApi", {
      apiName: `job-tracker-${props.stage}`,
      corsPreflight: {
        allowOrigins: [props.webOrigin],
        allowMethods: [
          CorsHttpMethod.GET,
          CorsHttpMethod.POST,
          CorsHttpMethod.PATCH,
          CorsHttpMethod.DELETE,
          CorsHttpMethod.OPTIONS,
        ],
        allowHeaders: ["content-type", "x-requested-with"],
        allowCredentials: true, // session cookie
      },
    });

    const integration = new HttpLambdaIntegration("ApiIntegration", this.handler);
    this.httpApi.addRoutes({
      path: "/api/{proxy+}",
      methods: [
        HttpMethod.GET,
        HttpMethod.POST,
        HttpMethod.PATCH,
        HttpMethod.DELETE,
      ],
      integration,
    });

    // Microsoft sign-in config. The redirect URI is derived from the HTTP API's
    // own endpoint, so it's correct without a second deploy. Added after the
    // API exists (apiEndpoint is a deploy-time token), which avoids a circular
    // dependency with the integration above.
    const callbackUrl = `${this.httpApi.apiEndpoint}/api/auth/callback`;
    this.handler.addEnvironment("MS_CLIENT_ID", props.msClientId);
    this.handler.addEnvironment("MS_AUTHORITY", props.msAuthority);
    this.handler.addEnvironment("MS_REDIRECT_URI", callbackUrl);

    new cdk.CfnOutput(this, "ApiUrl", { value: this.httpApi.apiEndpoint });
    // the exact string to register in the Entra app (Authentication -> Web)
    new cdk.CfnOutput(this, "MsRedirectUri", { value: callbackUrl });
  }
}
