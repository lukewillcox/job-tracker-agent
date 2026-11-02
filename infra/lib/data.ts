import * as cdk from "aws-cdk-lib";
import * as dynamodb from "aws-cdk-lib/aws-dynamodb";
import * as kms from "aws-cdk-lib/aws-kms";
import * as s3 from "aws-cdk-lib/aws-s3";
import * as sqs from "aws-cdk-lib/aws-sqs";
import { Construct } from "constructs";
import { Stage } from "./shared";

export interface DataProps {
  readonly stage: Stage;
}

/**
 * Core data layer (tasks.md task 3):
 *  - DynamoDB single table `JobTracker` with GSI1/GSI2, PITR and a stream
 *  - a customer-managed KMS key for refresh tokens
 *  - the SQS scan queue + DLQ and the prep queue + DLQ
 *  - a scratch S3 bucket for the ingest->classify "claim check" (the shortlist
 *    of messages is too large to pass through Step Functions' 256KB state
 *    limit, so ingest writes it to S3 and classify reads it back). Objects
 *    auto-expire after 1 day so email bodies never linger.
 */
export class Data extends Construct {
  readonly table: dynamodb.Table;
  readonly tokenKey: kms.Key;
  readonly scanQueue: sqs.Queue;
  readonly scanDlq: sqs.Queue;
  readonly prepQueue: sqs.Queue;
  readonly prepDlq: sqs.Queue;
  readonly scratchBucket: s3.Bucket;

  constructor(scope: Construct, id: string, props: DataProps) {
    super(scope, id);

    const isProd = props.stage === "prod";
    const removalPolicy = isProd ? cdk.RemovalPolicy.RETAIN : cdk.RemovalPolicy.DESTROY;

    this.tokenKey = new kms.Key(this, "TokenKey", {
      alias: `job-tracker/${props.stage}/refresh-tokens`,
      description: "Encrypts Microsoft refresh tokens at rest",
      enableKeyRotation: true,
      removalPolicy,
    });

    this.table = new dynamodb.Table(this, "Table", {
      tableName: `JobTracker-${props.stage}`,
      partitionKey: { name: "PK", type: dynamodb.AttributeType.STRING },
      sortKey: { name: "SK", type: dynamodb.AttributeType.STRING },
      billingMode: dynamodb.BillingMode.PAY_PER_REQUEST,
      pointInTimeRecoverySpecification: { pointInTimeRecoveryEnabled: true },
      encryption: dynamodb.TableEncryption.AWS_MANAGED,
      timeToLiveAttribute: "ttl",
      // stream drives prep-pack generation when furthest stage reaches Interview
      stream: dynamodb.StreamViewType.NEW_AND_OLD_IMAGES,
      removalPolicy,
    });

    // GSI1: reminder sweeper buckets (REMIND#{bucket} / USER#{uid}#DEADLINE#{id})
    this.table.addGlobalSecondaryIndex({
      indexName: "GSI1",
      partitionKey: { name: "GSI1PK", type: dynamodb.AttributeType.STRING },
      sortKey: { name: "GSI1SK", type: dynamodb.AttributeType.STRING },
      projectionType: dynamodb.ProjectionType.ALL,
    });

    // GSI2: ops / active-user listing (ACTIVE_USERS / USER#{uid})
    this.table.addGlobalSecondaryIndex({
      indexName: "GSI2",
      partitionKey: { name: "GSI2PK", type: dynamodb.AttributeType.STRING },
      sortKey: { name: "GSI2SK", type: dynamodb.AttributeType.STRING },
      projectionType: dynamodb.ProjectionType.KEYS_ONLY,
    });

    this.scanDlq = new sqs.Queue(this, "ScanDlq", {
      queueName: `job-tracker-${props.stage}-scan-dlq`,
      retentionPeriod: cdk.Duration.days(14),
      enforceSSL: true,
    });
    this.scanQueue = new sqs.Queue(this, "ScanQueue", {
      queueName: `job-tracker-${props.stage}-scan`,
      visibilityTimeout: cdk.Duration.minutes(6),
      enforceSSL: true,
      deadLetterQueue: { queue: this.scanDlq, maxReceiveCount: 3 },
    });

    this.prepDlq = new sqs.Queue(this, "PrepDlq", {
      queueName: `job-tracker-${props.stage}-prep-dlq`,
      retentionPeriod: cdk.Duration.days(14),
      enforceSSL: true,
    });
    this.prepQueue = new sqs.Queue(this, "PrepQueue", {
      queueName: `job-tracker-${props.stage}-prep`,
      visibilityTimeout: cdk.Duration.minutes(5),
      enforceSSL: true,
      deadLetterQueue: { queue: this.prepDlq, maxReceiveCount: 3 },
    });

    this.scratchBucket = new s3.Bucket(this, "ScanScratch", {
      bucketName: `job-tracker-${props.stage}-scan-scratch-${cdk.Aws.ACCOUNT_ID}`,
      blockPublicAccess: s3.BlockPublicAccess.BLOCK_ALL,
      encryption: s3.BucketEncryption.S3_MANAGED,
      enforceSSL: true,
      lifecycleRules: [{ expiration: cdk.Duration.days(1) }],
      removalPolicy: cdk.RemovalPolicy.DESTROY,
      autoDeleteObjects: true,
    });
  }
}
