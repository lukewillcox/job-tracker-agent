import * as cdk from "aws-cdk-lib";
import * as cloudfront from "aws-cdk-lib/aws-cloudfront";
import * as origins from "aws-cdk-lib/aws-cloudfront-origins";
import * as s3 from "aws-cdk-lib/aws-s3";
import { Construct } from "constructs";
import { Stage } from "./shared";

export interface WebProps {
  readonly stage: Stage;
}

/**
 * Frontend hosting (tech.md: S3 + CloudFront). A private bucket fronted by
 * CloudFront with Origin Access Control; SPA routing sends 403/404 to
 * index.html. The actual site contents are uploaded by the web build pipeline.
 */
export class Web extends Construct {
  readonly bucket: s3.Bucket;
  readonly distribution: cloudfront.Distribution;

  constructor(scope: Construct, id: string, props: WebProps) {
    super(scope, id);

    this.bucket = new s3.Bucket(this, "SiteBucket", {
      bucketName: `job-tracker-${props.stage}-web-${cdk.Aws.ACCOUNT_ID}`,
      blockPublicAccess: s3.BlockPublicAccess.BLOCK_ALL,
      encryption: s3.BucketEncryption.S3_MANAGED,
      enforceSSL: true,
      removalPolicy:
        props.stage === "prod" ? cdk.RemovalPolicy.RETAIN : cdk.RemovalPolicy.DESTROY,
      autoDeleteObjects: props.stage !== "prod",
    });

    this.distribution = new cloudfront.Distribution(this, "Distribution", {
      defaultBehavior: {
        origin: origins.S3BucketOrigin.withOriginAccessControl(this.bucket),
        viewerProtocolPolicy: cloudfront.ViewerProtocolPolicy.REDIRECT_TO_HTTPS,
        cachePolicy: cloudfront.CachePolicy.CACHING_OPTIMIZED,
      },
      defaultRootObject: "index.html",
      // SPA: serve index.html for client-side routes
      errorResponses: [
        { httpStatus: 403, responseHttpStatus: 200, responsePagePath: "/index.html" },
        { httpStatus: 404, responseHttpStatus: 200, responsePagePath: "/index.html" },
      ],
      // When a custom domain + ACM cert is added, set:
      //   domainNames, certificate, minimumProtocolVersion: TLS_V1_2_2021
      // The default CloudFront cert fixes the security policy, so it's omitted here.
    });

    new cdk.CfnOutput(this, "WebUrl", {
      value: `https://${this.distribution.distributionDomainName}`,
    });
  }
}
