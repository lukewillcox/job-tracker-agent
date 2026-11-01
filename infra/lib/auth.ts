import * as cdk from "aws-cdk-lib";
import * as secretsmanager from "aws-cdk-lib/aws-secretsmanager";
import { Construct } from "constructs";
import { Stage } from "./shared";

export interface AuthProps {
  readonly stage: Stage;
}

/**
 * App secrets (task 3): the Microsoft confidential-client secret and the
 * session-cookie signing key. Both are created empty and populated out of band
 * (the client secret from the Entra app registration; the signing key generated
 * once). Nothing here logs or exposes the values.
 */
export class Auth extends Construct {
  readonly appSecrets: secretsmanager.Secret;

  constructor(scope: Construct, id: string, props: AuthProps) {
    super(scope, id);

    this.appSecrets = new secretsmanager.Secret(this, "AppSecrets", {
      secretName: `job-tracker/${props.stage}/app`,
      description: "Microsoft client secret and session signing key",
      // generate the session signing key; the MS client secret is filled in later
      generateSecretString: {
        secretStringTemplate: JSON.stringify({ ms_client_secret: "" }),
        generateStringKey: "session_signing_key",
        excludePunctuation: true,
        passwordLength: 64,
      },
      removalPolicy:
        props.stage === "prod" ? cdk.RemovalPolicy.RETAIN : cdk.RemovalPolicy.DESTROY,
    });
  }
}
