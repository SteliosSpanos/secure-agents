# SecureAgents: Zero-Trust AI Document Pipeline
 
![API Deploy](https://github.com/SteliosSpanos/secure-agents/actions/workflows/deploy-api.yml/badge.svg)
![Worker Deploy](https://github.com/SteliosSpanos/secure-agents/actions/workflows/deploy-worker.yml/badge.svg)
 
**Upload a sensitive PDF and get back an AI-generated summary, without the document ever leaving a private AWS network.**
 
SecureAgents is a high-security, B2B SaaS infrastructure designed for industries where data privacy is non-negotiable (Legal, Medical, Finance). It provides a fully automated pipeline that ingests sensitive PDF documents, processes them using private AI models, and returns structured insights, all while ensuring the data never touches the public internet.
 
---
 
## Table of Contents
 
- [Demo & Architecture Overview](#demo--architecture-overview)
- [Tech Stack](#tech-stack)
- [Project Structure](#project-structure)
- [Zero-Trust Security & Isolation Architecture](#zero-trust-security--isolation-architecture)
- [Detailed Request Lifecycle](#detailed-request-lifecycle)
- [Low-Code & No-Code Integration](#low-code--no-code-integration)
- [Key Architectural Decisions (ADRs)](#key-architectural-decisions-adrs)
- [CloudWatch & Observability](#cloudwatch--observability)
- [Estimated Monthly Costs](#estimated-monthly-costs)
- [Prerequisites & Environment Setup](#prerequisites--environment-setup)
- [Deployment](#deployment)
- [GitHub Actions & CI/CD Pipeline](#github-actions--cicd-pipeline)
- [Operational Runbooks](#operational-runbooks)
- [API Reference](#api-reference)
- [Data Handling Policy](#data-handling-policy)
- [License](#license)
---
 
## Demo & Architecture Overview
 
<!-- TODO: Paste Loom video link/embed here -->
 
A short walkthrough of the full request lifecycle, from requesting an upload slot through webhook delivery, plus a visual overview of the zero-trust architecture.
 
---
 
## Tech Stack
 
**Backend:** Python 3.11 (FastAPI, boto3, pypdf) · Python 3.13 (AWS Lambda)
**Infrastructure:** Terraform · AWS (ECS, ECR, CloudFront, EC2, KMS, S3, DynamoDB, Lambda, WAF, APIGW, CloudWatch, SQS, IAM, Bedrock) · Docker 
**Data & Messaging:** DynamoDB · SQS · S3
**AI:** Amazon Bedrock (Claude 3 Haiku)
**Security:** IAM (OIDC) · KMS · Lambda Authorizer (HMAC)
**CI/CD:** GitHub Actions (OIDC auth, per-service pipelines, ECS smoke testing)
 
---
 
## Project Structure
 
```text
.
├── .github/workflows/      # CI/CD: per-service lint/test/deploy + manual rollback
├── agent-api/              # FastAPI application v1.0.1 (Ingress & Status)
├── agent-worker/           # Python 3.11 worker (PDF Processing & Bedrock AI)
├── bootstrap/              # Terraform for remote state (S3/DynamoDB)
├── lambda-authorizer/      # Zero-Trust HMAC & Origin validation logic
├── lambda-webhook-trigger/ # DynamoDB Stream consumer (Triggers notifications)
├── lambda-webhook-consumer/# Secure Webhook delivery (HMAC Signatures)
├── scripts/                # Management scripts (API Key & Webhook setup)
└── terraform/              # Main infrastructure (VPC, ECS, WAF, etc.)
```
 
---
 
## Zero-Trust Security & Isolation Architecture
 
SecureAgents is built on a "Deny-by-Default" principle. Below are the key pillars of our isolation strategy:
 
### 1. Zero-Egress VPC Design
 
- **Private Subnets & NAT Instances:** All compute resources (ECS Fargate) live in strictly private subnets. Egress for maintenance and updates is routed through cost-optimized **NAT Instances** rather than expensive NAT Gateways.
- **VPC Endpoints (PrivateLink):** Critical communication with AWS services (S3, DynamoDB, SQS, KMS, Bedrock) occurs entirely over the AWS private network backbone via Interface and Gateway Endpoints.
- **Security Group Hardening:** Egress is restricted to only the necessary VPC Endpoints and NAT routes, preventing data exfiltration even if a container is compromised.
- **Resource-Based Policies:** S3 and DynamoDB tables have policies that explicitly `Deny` any traffic that does not originate from the specific VPC Endpoints.
### 2. The "Double-Shield" Ingress & Audit Trail
 
- **Edge Protection:** Traffic first hits AWS WAF (Rate Limiting + Managed Rule Sets) and CloudFront.
- **Native Header Validation:** API Gateway performs native `identity_source` checks for both the API Key and the `X-Origin-Verify` secret, rejecting unauthorized direct traffic before it even invokes the Lambda Authorizer.
- **Secure Authorizer:** The Lambda Authorizer validates HMAC-based API keys against hashed records in DynamoDB, ensuring zero-knowledge storage of sensitive keys.
- **VPC Link:** API Gateway connects to an **Internal-Only Application Load Balancer** via a VPC Link, ensuring the ALB has no public DNS or IP address.
### 3. Application Resilience & S3 Hardening
 
- **S3 Bucket Hardening:** All buckets use **BucketOwnerEnforced** ownership controls, disabling ACLs and ensuring all objects are owned by the account.
- **Streaming PDF Processing:** The AI worker utilizes a memory-efficient streaming strategy for PDF extraction, downloading documents to temporary local storage rather than RAM.
- **Size & Content Limits:** The system enforces a strict maximum file size (**50MB**) and truncates extracted text (15,000 characters) to prevent LLM context window overflows and "token-bomb" cost attacks.
- **Graceful Shutdown (SIGTERM):** Workers are programmed to rescue active jobs during Fargate scale-in events. If a worker receives a SIGTERM, it attempts to revert the job state to `PENDING_UPLOAD` and releases the SQS message before exiting.
### 4. Asynchronous Webhook Delivery
 
- **Event-Driven:** Once a job is `COMPLETED`, a DynamoDB Stream triggers a Lambda to queue a notification.
- **Guaranteed Delivery:** SQS handles retries for webhook deliveries, moving failed notifications to a Dead Letter Queue (DLQ) after 3 attempts.
- **Cryptographic Security:** Every webhook delivery includes an **HMAC-SHA256 signature** (`X-SecureAgents-Signature`), allowing clients to verify that the notification originated from SecureAgents.
---
 
## Detailed Request Lifecycle
 
SecureAgents utilizes a four-phase asynchronous pipeline designed for zero-trust isolation and high-volume processing.
 
### Phase 1: The Negotiation (Handshake)
The client does not send documents to the API. Instead, they request a "secure ticket" to upload directly to S3.
1. **Request:** Client sends `POST /api/v1/request-upload` with their `x-api-key`.
2. **Double-Shield Validation:** WAF and API Gateway perform native header checks (`x-api-key` + `x-origin-verify`) before any compute is invoked.
3. **Authorization:** A Lambda Authorizer verifies the key hash in DynamoDB and returns a secure `client_id` context.
4. **Presigned Ticket:** The FastAPI backend initializes a job record and returns an **S3 Presigned POST URL** containing a set of `required_fields` (security tokens and metadata).

![Architecture Diagram 1](./assets/secure-agents-1.svg)
 
### Phase 2: Ingestion (Direct Secure Upload)
 
The client uploads the PDF directly to S3, bypassing the API to ensure performance and security.
 
#### Mechanism
The client performs a multipart `POST` request directly to the provided S3 URL.
 
#### Mandatory Metadata
To successfully complete the upload, the client must include all the `required_fields` generated during Phase 1. These critical security fields include:
* **`x-amz-server-side-encryption`**: Forces AES-256 encryption via AWS KMS before the file is saved.
* **`x-amz-server-side-encryption-aws-kms-key-id`**: Specifies the exact KMS Key ARN that S3 must use for the encryption.
* **`x-amz-meta-client-id`**: Cryptographically ties the uploaded object to the specific client/owner.
* **`x-amz-meta-job-id`**: Links the file directly to the initialized processing job in the database.
* **`Content-Type`**: Must be explicitly set to `application/pdf` to prevent malicious or unsupported file types from being ingested.

#### Native Validation
Amazon S3 natively verifies the backend-generated cryptographic signature upon receiving the request. If the client attempts to tamper with any metadata, alters the expected content type, or if the file size exceeds the **50MB limit**, S3 will instantly reject the upload and return a **403 Forbidden** error.
 
![Architecture Diagram 2](./assets/secure-agents-2.svg)
 
### Phase 3: Transformation (AI Pipeline)
The system processes the document in a fully isolated, zero-egress environment.
1. **Trigger:** S3 triggers an event notification to an SQS Work Queue.
2. **Orchestration:** An AI Worker (Fargate) pulls the task and marks the job as `PROCESSING`.
3. **Privacy-First Inference:** The worker extracts text and invokes **Claude 3 Haiku** via a VPC Endpoint. Data travels over the AWS private backbone, never the public internet.
4. **Finalization:** The summary is saved to DynamoDB, and the status moves to `COMPLETED`.

![Architecture Diagram 3](./assets/secure-agents-3.svg)
 
### Phase 4: Notification (Asynchronous Webhook)
 
The client is notified instantly when their document is ready, completely eliminating the need for inefficient, constant API polling. This architecture utilizes a decoupled queue system to guarantee delivery even if the client's endpoint experiences temporary downtime.
 
#### Mechanism & Orchestration
* **Event Trigger:** As soon as the AI Worker updates the job status, a **DynamoDB Stream** detects the `COMPLETED` state and fires an event.
* **Event Routing:** A **Lambda Webhook Trigger** catches the stream event and pushes a notification message into an **SQS Webhook Queue**. 
* **Decoupled Processing:** A separate **Lambda Webhook Consumer** polls the SQS queue, pulling messages for final delivery. This decoupling allows for robust retry mechanisms and Dead Letter Queues (DLQs) if a client endpoint is unreachable.

#### Secure Delivery (Signed Webhooks)
To guarantee that the webhook is authentic and hasn't been intercepted or tampered with:
1. **Secret Retrieval:** The Lambda Webhook Consumer queries DynamoDB to fetch the client's designated webhook URL and their unique `webhook_secret`.
2. **Cryptographic Signing:** The Lambda signs the JSON payload using the **HMAC-SHA256** algorithm.
3. **Dispatch:** A `POST` request containing the job summary is sent directly to the client's endpoint. 

#### Client Validation
The client receives the `X-SecureAgents-Signature` header alongside the payload. By hashing the incoming body with their local copy of the `webhook_secret`, the client can perfectly verify the payload's origin and integrity before processing the AI-generated summary.
 
![Architecture Diagram 4](./assets/secure-agents-4.svg)

---
 
## Low-Code & No-Code Integration
SecureAgents is designed to be "Integration-Ready" for tools like **Make.com**, **Zapier**, and **n8n**.
 
- **Simplified Ingestion:** Low-code users can map the `required_fields` from the API response directly into an HTTP module to handle direct S3 uploads without writing code.
- **Automation Ready:** Webhooks allow for instant triggers in CRM platforms (Salesforce, HubSpot) or collaboration tools (Slack, Microsoft Teams) as soon as document processing is finished.

---
 
## Key Architectural Decisions (ADRs)
 
1.  **Claude 3 Haiku (Amazon Bedrock):**
    - **Decision:** Use `anthropic.claude-3-haiku-20240307-v1:0` via Bedrock.
    - **Why?** Haiku provides the optimal balance of speed, cost, and intelligence for high-density document summarization. It is significantly faster and more cost-effective than larger models while maintaining excellent instruction following.
2.  **NAT Instances vs NAT Gateways:**
    - **Decision:** Use managed NAT Instances (t3.micro) for outbound traffic.
    - **Why?** For a low-egress B2B SaaS, NAT Gateways (~$32/month/AZ) are unnecessarily expensive. NAT instances provide the same functionality at a fraction of the cost (~$7/month).
3.  **Asynchronous HMAC Webhooks:**
    - **Decision:** Implement a SQS-backed webhook system with SHA256 signatures.
    - **Why?** Eliminates the need for clients to poll for status. SQS ensures we don't lose notifications if the client's endpoint is briefly down. HMAC signatures allow clients to securely trust the data without public IP whitelisting.
4.  **Native Identity Source Validation:**
    - **Decision:** Perform header checks at the API Gateway level.
    - **Why?** Prevents unauthorized requests from even invoking our Lambda Authorizer, saving on compute costs and reducing the attack surface.

---
 
## CloudWatch & Observability
 
SecureAgents includes a comprehensive monitoring suite to ensure security and operational stability:
 
### 1. Centralized Logging
All system logs are encrypted with Customer Managed Keys (CMKs) and retained for 30 days:
- **API & Worker Logs:** Full application traces from ECS Fargate.
- **VPC Flow Logs:** Captures all IP traffic within the VPC for security auditing.
- **Audit Trails:** Specialized logs for **WAF (Edge)**, **API Gateway (Entry)**, and **S3 (Storage Access)**.
- **Infrastructure Logs:** Boot logs for **NAT Instances** and **Jump Boxes**.

### 2. Proactive Alerting (SNS)
High-priority alerts are sent via SNS to the developer team:
- **Security Alerts:** Triggered by **GuardDuty Findings** (Severity >= 7).
- **Processing Failures:** Fires if the **Agent DLQ** or **Webhook DLQ** receives a failed message.
- **Infrastructure Health:** Alerts for **NAT Instance status check failures** or **High ALB 5XX error rates**.
- **Performance Bottlenecks:** Alerts for **High ALB Latency (>1s)** or **SQS Stalling** (messages older than 20 mins).

### 3. Operational Dashboard
A centralized CloudWatch Dashboard provides real-time visibility into:
- **Traffic Health:** Request counts vs. 5XX error rates.
- **Queue Performance:** Tasks waiting, tasks in progress, and webhook backlog status.
---
 
## Estimated Monthly Costs
 
| Service                | Estimated Cost   | Logic                                                     |
| :--------------------- | :--------------- | :-------------------------------------------------------- |
| **Edge Defense (WAF)** | ~$7 - $15        | Base cost for Web ACL + Rate Limit rules.                 |
| **VPC Endpoints**      | ~$115 - $140     | 9x Endpoints (S3, SQS, KMS, Bedrock, ECR, etc.) in 2 AZs. |
| **Compute (Fargate)**  | ~$25 - $40       | 2x small API tasks + fluctuating workers (scales to 0).   |
| **NAT Instances**      | ~$14             | 2x t3.micro instances (one per AZ) vs ~$64 for NAT GW.    |
| **Load Balancing**     | ~$20             | Internal ALB base cost for high availability.             |
| **Database & Storage** | ~$5 - $10        | S3, DynamoDB, SQS (pay-per-request/GB) + Audit Logs.      |
| **AI (Bedrock)**       | Variable         | Billed per 1,000 tokens (Claude 3 Haiku is very cheap).   |
| **Total Base**         | **~$185 - $240** | Production-grade security for less than $8.00/day.        |
 
---
 
## Prerequisites & Environment Setup
 
### Required Tools
 
- **Terraform:** `>= 1.5`
- **Python:** `3.11` (Workers) / `3.13` (Lambdas)
- **AWS CLI:** `v2`
- **Docker:** (For building images)
## Deployment
 
**Phase 1: Bootstrap the Control Plane**
 
1. Navigate to `bootstrap/`.
2. Run `terraform init` and `terraform apply`.
3. Copy the backend configuration to `terraform/providers.tf`.
**Phase 2: Deploy the Application**
 
1. Navigate to `terraform/`.
2. Run `terraform init` and `terraform apply`.
---
 
## GitHub Actions & CI/CD Pipeline
 
Deployments are handled by four independent workflow files in `.github/workflows/`, split per-service so a change to one component doesn't rebuild or redeploy the other:
 
| Workflow | Trigger | Purpose |
|---|---|---|
| `reusable-checks.yml` | Called by the two deploy workflows (not triggered directly) | Runs Ruff lint + format checks, and the pytest suite (with an 80% coverage floor) for whichever service calls it |
| `deploy-api.yml` | Push to `main` touching `agent-api/**` | Builds, tests, and deploys the FastAPI service |
| `deploy-worker.yml` | Push to `main` touching `agent-worker/**` | Builds, tests, and deploys the AI worker, including a real ECS smoke test before promoting |
| `rollback.yml` | Manual (`workflow_dispatch`) only | Redeploys a previous image for either service on demand |
 
### Build & Deploy Flow
 
Each deploy workflow runs lint + tests, builds the Docker image, smoke-tests it locally (a clean import of the app with dummy config, catching broken dependencies or import errors before anything is pushed), pushes the image to ECR, then registers a new ECS task definition revision.
 
For the worker specifically, that new revision is **run as a real ECS task before the live service is ever pointed at it**. It must stay healthy in the real network and IAM context for 20 seconds, or the deploy stops there and the currently running service is left untouched. Only a task definition revision that has passed this check gets promoted to `agents-worker-service`.
 
### Image Tagging & Rollback
 
ECR repositories use `IMMUTABLE` tags. Once an image is pushed under a tag (the git commit SHA), that tag can never be repointed to different content, closing off a class of supply-chain attack where a tag is silently swapped after deployment. Because tags can't move, "what's currently live and known-good" is tracked separately: each successful deploy writes its SHA to an SSM Parameter (`/agents/api/last-stable-sha`, `/agents/worker/last-stable-sha`).
 
To roll back, run the **Rollback** workflow manually from the Actions tab, choose `api` or `worker`, and optionally provide a specific SHA. Leaving it blank rolls back to whatever SHA is currently recorded in SSM.
 
### Authentication
 
All workflows authenticate to AWS via OIDC federation (`GithubActionsRole`) — no long-lived AWS credentials are stored in GitHub at any point.
 
---
 
## Operational Runbooks
 
### 1. Rotating Client API Keys & Webhooks
 
Use the management script to generate or revoke access:
 
```bash
# Generate a new key with an optional webhook
python scripts/client_script.py --generate --client-id "ClientName" --webhook-url "https://api.client.com/webhook"
 
# Deactivate a key (schedules deletion in 90 days)
python scripts/client_script.py --deactivate --key "ak_live_..."
```
 
### 2. Monitoring Webhook Failures
 
If webhooks fail to deliver, they move to the `agents-webhook-dlq`.
- **Check DLQ:** `aws sqs receive-message --queue-url <WEBHOOK_DLQ_URL>`
- **Check Logs:** `aws logs tail /aws/lambda/agents-webhook-consumer --follow`
---
 
## API Reference
 
### 1. Request Upload Slot
 
`POST /api/v1/request-upload`
 
**Headers:**
- `x-api-key: <your-api-key>`
- `x-origin-verify: <your-origin-token>`
**Body:**
 
```json
{
  "filename": "document.pdf"
}
```
 
### 2. Uploading the File (Direct to S3)
 
You must perform a `multipart/form-data` POST request to the S3 URL.
 
> **CRITICAL:** The metadata returned in `required_fields` from Step 1 must be appended as **Form Data fields**, not HTTP headers! Ensure these fields are appended **before** the actual file.
 
- `x-amz-server-side-encryption`: `aws:kms`
- `x-amz-server-side-encryption-aws-kms-key-id`: `<kms-key-arn>`
- `x-amz-meta-client-id`: `<client-id>`
- `x-amz-meta-job-id`: `<job-id>`
- `Content-Type`: `application/pdf`
- `file`: `<The actual PDF file buffer/blob>` (Must be the last field)
### 3. Receiving Webhooks
 
Your endpoint will receive a `POST` request once the AI pipeline finishes processing:
 
**Headers:**
- `X-SecureAgents-Signature: <hmac-sha256-hash>` (Note: validate this hash using your webhook secret to ensure the payload came from our system)
**Body:**
 
```json
{
  "event": "JOB_COMPLETED",
  "job_id": "uuid",
  "status": "COMPLETED",
  "result_summary": "..."
}
```
 
---
 
## Data Handling Policy
 
- **Jobs Table:** Records expire after **30 days** (via TTL).
- **S3 Storage:** Documents are automatically purged after **30 days**.
- **Audit Logs:** Retained for **90 days**.
- **Point-In-Time Recovery:** Enabled for all DynamoDB tables.

---
 
## License
MIT License. See [LICENSE](LICENSE) for details.

