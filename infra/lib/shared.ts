import * as path from "node:path";
import * as cdk from "aws-cdk-lib";
import * as lambda from "aws-cdk-lib/aws-lambda";
import * as logs from "aws-cdk-lib/aws-logs";
import { Construct } from "constructs";

/** Create a 30-day-retention log group for a function (task 3). */
function logGroupFor(scope: Construct, id: string, stage: Stage): logs.LogGroup {
  return new logs.LogGroup(scope, `${id}Logs`, {
    retention: logs.RetentionDays.ONE_MONTH,
    removalPolicy:
      stage === "prod" ? cdk.RemovalPolicy.RETAIN : cdk.RemovalPolicy.DESTROY,
  });
}

export type Stage = "dev" | "prod";

/** Absolute path to the Python backend, used as the Lambda asset root. */
export const BACKEND_ROOT = path.join(__dirname, "..", "..", "backend");

/** Where build-layer.sh installs the runtime dependencies. */
const LAYER_ROOT = path.join(__dirname, "..", "layer-build");

/**
 * Get (or lazily create) the single shared dependencies layer for a stack.
 *
 * The asset is `infra/layer-build/`, populated by `scripts/build-layer.sh`
 * before deploy. If it hasn't been built the directory is still created empty
 * so `cdk synth` succeeds offline; a deploy without building would ship an
 * empty layer, so the deploy docs call the build step out explicitly.
 */
function depsLayer(scope: Construct, stage: Stage): lambda.LayerVersion {
  const stack = cdk.Stack.of(scope);
  const existing = stack.node.tryFindChild("DepsLayer");
  if (existing) {
    return existing as lambda.LayerVersion;
  }
  // ensure the asset directory exists even before the build script runs
  const fs = require("node:fs") as typeof import("node:fs");
  fs.mkdirSync(path.join(LAYER_ROOT, "python"), { recursive: true });
  return new lambda.LayerVersion(stack, "DepsLayer", {
    layerVersionName: `job-tracker-${stage}-deps`,
    code: lambda.Code.fromAsset(LAYER_ROOT),
    compatibleRuntimes: [lambda.Runtime.PYTHON_3_12],
    compatibleArchitectures: [lambda.Architecture.ARM_64],
    description: "Python runtime dependencies (built by scripts/build-layer.sh)",
  });
}

export interface PyFunctionProps {
  /**
   * Handler in "module.function" form relative to the backend root,
   * e.g. "api.auth.login_handler" or "agent.ingest.handler".
   */
  readonly handler: string;
  readonly description?: string;
  readonly timeout?: cdk.Duration;
  readonly memorySize?: number;
  readonly environment?: Record<string, string>;
  /** Reserve concurrency to bound Graph/Bedrock load (optional). */
  readonly reservedConcurrentExecutions?: number;
}

/**
 * Factory for the Python 3.12 Lambdas. One handler per file named per the
 * backend layout. The function code is the backend source (`Code.fromAsset`);
 * third-party runtime deps come from the shared layer built by
 * `scripts/build-layer.sh`. Both work offline for `cdk synth`.
 */
export function pyFunction(
  scope: Construct,
  id: string,
  stage: Stage,
  props: PyFunctionProps,
): lambda.Function {
  return new lambda.Function(scope, id, {
    runtime: lambda.Runtime.PYTHON_3_12,
    architecture: lambda.Architecture.ARM_64,
    code: lambda.Code.fromAsset(BACKEND_ROOT, {
      exclude: [
        ".venv",
        "tests",
        "**/__pycache__",
        ".pytest_cache",
        ".mypy_cache",
        ".ruff_cache",
        "*.md",
      ],
    }),
    handler: props.handler,
    description: props.description,
    timeout: props.timeout ?? cdk.Duration.seconds(30),
    memorySize: props.memorySize ?? 512,
    // Reserved concurrency is prod-only. New accounts default to a total Lambda
    // concurrency of 10 with a mandatory 10-unit unreserved floor, so any
    // reservation in dev is rejected. Classify fan-out is still bounded by the
    // Step Functions Map (maxConcurrency), which needs no account reservation.
    reservedConcurrentExecutions:
      stage === "prod" ? props.reservedConcurrentExecutions : undefined,
    layers: [depsLayer(scope, stage)], // runtime deps (pydantic, msal, openpyxl, ...)
    tracing: lambda.Tracing.ACTIVE, // X-Ray (tech.md)
    logGroup: logGroupFor(scope, id, stage), // 30-day retention (task 3)
    environment: {
      STAGE: stage,
      POWERTOOLS_SERVICE_NAME: "job-tracker",
      POWERTOOLS_METRICS_NAMESPACE: "JobTracker",
      LOG_LEVEL: "INFO",
      ...props.environment,
    },
  });
}
