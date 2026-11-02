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
// IMPORTANT: confirm the exact ids/inference-profile ids enabled in YOUR account
// and region before deploy (see README "Enabling Bedrock models"). In eu-north-1
// most current Claude models are only callable via a regional inference profile
// id (prefixed `eu.`), e.g. `eu.anthropic.claude-haiku-5-5-...`. Override with:
//   cdk deploy -c classifierModelId=... -c prepModelId=... -c sesDomain=...
const classifierModelId =
  app.node.tryGetContext("classifierModelId") ?? "SET_ME_classifier_model_id";
const prepModelId =
  app.node.tryGetContext("prepModelId") ?? "SET_ME_prep_model_id";
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
