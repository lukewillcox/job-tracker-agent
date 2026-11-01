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
 * backend layout. Uses `Code.fromAsset` on the backend directory so `cdk synth`
 * works offline (no Docker bundling); a real build step would install deps into
 * the asset or attach a dependencies layer before deploy.
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
    reservedConcurrentExecutions: props.reservedConcurrentExecutions,
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
