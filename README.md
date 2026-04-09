# Secure AI Agents

A B2B SaaS platform providing autonomous AI agents for SMBs (law firms, medical clinics, accountants) with a focus on **absolute data privacy and GDPR compliance**. This system utilizes a Zero-Trust AWS architecture, ephemeral containerization, and kernel-level security to ensure sensitive client data remains private and secure.

---

## System Architecture & Workflow

The system is built as an asynchronous, event-driven data pipeline to maximize security and minimize idle cloud costs.

| Component                      | Description                 | Role                                                                               |
| :----------------------------- | :-------------------------- | :--------------------------------------------------------------------------------- |
| **API Gateway / ALB**          | Application Load Balancer   | Secure ingress for the Ingest API, terminating SSL and routing traffic to Fargate. |
| **Ingest API (FastAPI)**       | Fargate Container Service   | Validates uploads, stores them in S3, and initiates SQS tasks.                     |
| **Storage Vault (S3 & KMS)**   | Encrypted document storage  | Segmented by `tenant_id` with KMS encryption.                                      |
| **Message Queue (SQS)**        | Task buffering              | Ensures the AI worker can handle bulk uploads reliably.                            |
| **AI Agent Compute (Fargate)** | Ephemeral worker containers | Processes PDFs using LangChain and Bedrock, then self-destructs.                   |
| **Inference (Amazon Bedrock)** | Serverless AI access        | Provides access to LLMs (e.g., Llama 3) with zero data-training guarantees.        |
| **State DB (DynamoDB)**        | Job & Client tracking       | Stores job status and securely hashes API keys for verification.                   |

---

## Security Pillars (The Zero-Trust Moat)

| Feature                  | Technical Implementation | Security Benefit                                                               |
| :----------------------- | :----------------------- | :----------------------------------------------------------------------------- |
| **Network Isolation**    | VPC Endpoints            | Traffic routes internally; the agent has **no public internet access**.        |
| **Ephemeral Compute**    | AWS Fargate              | Containers exist only for the duration of the task (max 15 mins).              |
| **Kernel-Level Defense** | eBPF Monitoring          | Terminates containers attempting unauthorized system calls or network sockets. |
| **Least Privilege**      | IAM Scoped Roles         | Agent roles grant access _only_ to specific assigned S3 files.                 |
| **Data Encryption**      | AWS KMS                  | All client data is encrypted at rest and in transit.                           |

---

## Estimated Monthly AWS Costs (Approximate)

Based on a standard small-scale deployment (1 ALB + 2 small Fargate tasks).

| Service                  | Estimated Cost (Monthly) | Notes                                              |
| :----------------------- | :----------------------- | :------------------------------------------------- |
| **ALB**                  | ~$20.00 - $25.00         | Base price + LCU (Request processing).             |
| **Fargate (Ingest API)** | ~$10.00 - $15.00         | 0.5 vCPU / 1GB RAM (depends on uptime).            |
| **VPC Endpoints**        | ~$20.00 - $30.00         | Essential for Zero-Trust (S3, SQS, Bedrock, etc.). |
| **DynamoDB/SQS/S3**      | ~$1.00 - $5.00           | Pay-per-use (very low for small volumes).          |
| **Amazon Bedrock**       | Pay-as-you-go            | Based on tokens/inference usage.                   |
| **KMS**                  | ~$1.00                   | $1 per customer master key.                        |
| **Total Base Cost**      | **~$55.00 - $80.00**     | Excluding high-volume inference.                   |

---

## 🛠️ Technical Stack

| Category           | Technologies                                                       |
| :----------------- | :----------------------------------------------------------------- |
| **Backend**        | Python, FastAPI, Boto3                                             |
| **Infrastructure** | Terraform, AWS (VPC, ALB, ECS/Fargate, S3, SQS, DynamoDB, Bedrock) |
| **AI Framework**   | LangChain                                                          |
| **Security**       | eBPF, IAM Roles, VPC Interface Endpoints, KMS                      |

---

## Project Structure

```text
.
├── agent-api/                    # FastAPI backend service
│   ├── app/                      # Application source code
│   │   ├── aws_client.py         # AWS service wrappers (S3, SQS, DynamoDB)
│   │   ├── config.py             # Environment & App configuration
│   │   ├── __init__.py           # Package marker
│   │   └── main.py               # FastAPI routes & entry point
│   ├── client_key_script.py      # Script for generating/hashing client API keys
│   ├── Dockerfile                # Multi-stage Docker build for Fargate
│   └── requirements.txt          # Python dependencies
├── terraform/                    # Infrastructure as Code (AWS)
│   ├── backend.tf                # S3 backend for Terraform state
│   ├── data.tf                   # External data sources (AWS account info, etc.)
│   ├── dynamodb.tf               # NoSQL tables for jobs and API keys
│   ├── iam.tf                    # Task and execution roles
│   ├── iam_vpc.tf                # VPC Endpoint IAM policies
│   ├── kms.tf                    # Encryption key management
│   ├── network.tf                # VPC, Subnets, Security Groups, Endpoints
│   ├── providers.tf              # AWS provider configuration
│   ├── s3.tf                     # Encrypted document storage
│   ├── sqs.tf                    # Message queuing logic
│   ├── terraform.tfvars          # Environment-specific variables
│   └── variables.tf              # Terraform variable definitions
├── docker-compose.yml            # Local development environment (optional)
├── GEMINI.md                     # Project blueprint and roadmap
└── README.md                     # Project documentation
```

---

## API Endpoints

| Method | Endpoint                 | Description                                                |
| :----- | :----------------------- | :--------------------------------------------------------- |
| `GET`  | `/health`                | API health check.                                          |
| `POST` | `/api/v1/request-upload` | Request a secure, pre-signed upload URL for a PDF.         |
| `GET`  | `/api/v1/jobs/{job_id}`  | Check the status and results of a document processing job. |
