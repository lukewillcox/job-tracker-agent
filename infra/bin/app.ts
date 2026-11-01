#!/usr/bin/env node
import "source-map-support/register";
import * as cdk from "aws-cdk-lib";
import { AppStack } from "../lib/app-stack";

const app = new cdk.App();

// eu-west-2 (London) per tech.md. Account comes from the environment/profile.
const env: cdk.Environment = {
  account: process.env.CDK_DEFAULT_ACCOUNT,
  region: process.env.CDK_DEFAULT_REGION ?? "eu-west-2",
};

// Bedrock model ids and the SES domain come from context/config, not code.
// Defaults are the Claude model families used today; override per stage with
// `cdk deploy -c classifierModelId=... -c prepModelId=... -c sesDomain=...`.
const classifierModelId =
  app.node.tryGetContext("classifierModelId") ??
  "anthropic.claude-3-haiku-20240307-v1:0";
const prepModelId =
  app.node.tryGetContext("prepModelId") ??
  "anthropic.claude-3-5-sonnet-20240620-v1:0";
const sesSendingDomain = app.node.tryGetContext("sesDomain") ?? "mail.example.com";

for (const stage of ["dev", "prod"] as const) {
  new AppStack(app, `JobTracker-${stage}`, {
    env,
    stage,
    classifierModelId,
    prepModelId,
    sesSendingDomain,
    description: `Job Tracker Agent (${stage})`,
  });
}

app.synth();
