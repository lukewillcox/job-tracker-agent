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

// All of the following come from context/config, never hard-coded in app code.
//
// Bedrock inference-profile ids confirmed enabled in eu-north-1 (Stockholm):
//   classifier -> Claude Haiku 5.5, prep packs -> Claude Sonnet 5.5.
// In eu-north-1 Claude is invoked via a regional inference profile (prefixed
// `eu.`). The 5.5 profiles are floating aliases (no dated/pinned variant exists
// in this region yet). Override per stage/account with:
//   cdk deploy -c classifierModelId=... -c prepModelId=... \
//              -c sesFromAddress=... -c msClientId=...
const classifierModelId =
  app.node.tryGetContext("classifierModelId") ?? "eu.anthropic.claude-haiku-5-5";
const prepModelId =
  app.node.tryGetContext("prepModelId") ?? "eu.anthropic.claude-sonnet-5-5";

// SES sender identity. In the sandbox this must be a verified address, and is
// also the only allowed recipient. Dev default = the verified personal address.
const sesFromAddress =
  app.node.tryGetContext("sesFromAddress") ?? "luke.willcox@outlook.com";

// Microsoft sign-in: dev Entra app (client) id; "common" accepts any tenant +
// personal Microsoft accounts.
const msClientId =
  app.node.tryGetContext("msClientId") ?? "8f599315-1e39-4015-9924-fb0bf1e92974";
const msAuthority =
  app.node.tryGetContext("msAuthority") ?? "https://login.microsoftonline.com/common";

for (const stage of ["dev", "prod"] as const) {
  new AppStack(app, `JobTracker-${stage}`, {
    env,
    stage,
    classifierModelId,
    prepModelId,
    sesFromAddress,
    msClientId,
    msAuthority,
    description: `Job Tracker Agent (${stage})`,
  });
}

app.synth();
