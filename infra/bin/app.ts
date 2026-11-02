#!/usr/bin/env node
import "source-map-support/register";
import * as cdk from "aws-cdk-lib";
import { AppStack } from "../lib/app-stack";

const app = new cdk.App();

// eu-north-1 (Stockholm) per tech.md. Account comes from the environment/profile.
const env: cdk.Environment = {
  account: process.env.CDK_DEFAULT_ACCOUNT,
  region: process.env.CDK_DEFAULT_REGION ?? "eu-north-1",
};

// Bedrock model ids and the SES domain come from context/config, not code.
// Bedrock inference-profile ids confirmed enabled in eu-north-1 (Stockholm):
//   classifier -> Claude Haiku 4.5, prep packs -> Claude Sonnet 4.5.
// In eu-north-1 Claude is invoked via a regional inference profile (prefixed
// `eu.`), not the bare model id. Override per stage/account with:
//   cdk deploy -c classifierModelId=... -c prepModelId=... -c sesDomain=...
const classifierModelId =
  app.node.tryGetContext("classifierModelId") ??
  "eu.anthropic.claude-haiku-4-5-20251001-v1:0";
const prepModelId =
  app.node.tryGetContext("prepModelId") ??
  "eu.anthropic.claude-sonnet-4-5-20250929-v1:0";
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
