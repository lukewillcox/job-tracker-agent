import * as cdk from "aws-cdk-lib";
import { Construct } from "constructs";
import { Api } from "./api";
import { Auth } from "./auth";
import { Data } from "./data";
import { Notify } from "./notify";
import { Scan } from "./scan";
import { Stage } from "./shared";
import { Web } from "./web";

export interface AppStackProps extends cdk.StackProps {
  readonly stage: Stage;
  /** Bedrock model ids (tech.md: from config, never hard-coded in app code). */
  readonly classifierModelId: string;
  readonly prepModelId: string;
  /** Verified SES sender identity (an address in sandbox, a domain later). */
  readonly sesFromAddress: string;
  /** Microsoft Entra app (client) id and sign-in authority. */
  readonly msClientId: string;
  readonly msAuthority: string;
}

/**
 * One stack per stage, composing the area constructs from structure.md:
 * data, auth, web, notify, scan, api. Composed in a single stack (rather than
 * many) to avoid brittle cross-stack exports; each area stays its own construct.
 */
export class AppStack extends cdk.Stack {
  constructor(scope: Construct, id: string, props: AppStackProps) {
    super(scope, id, props);

    const data = new Data(this, "Data", { stage: props.stage });
    const auth = new Auth(this, "Auth", { stage: props.stage });
    const web = new Web(this, "Web", { stage: props.stage });

    const webOrigin = `https://${web.distribution.distributionDomainName}`;

    const notify = new Notify(this, "Notify", {
      stage: props.stage,
      data,
      auth,
      sesFromAddress: props.sesFromAddress,
      prepModelId: props.prepModelId,
    });

    new Scan(this, "Scan", {
      stage: props.stage,
      data,
      auth,
      notify,
      classifierModelId: props.classifierModelId,
      prepModelId: props.prepModelId,
    });

    new Api(this, "Api", {
      stage: props.stage,
      data,
      auth,
      webOrigin,
      msClientId: props.msClientId,
      msAuthority: props.msAuthority,
    });
  }
}
