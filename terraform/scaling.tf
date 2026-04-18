/*
    Auto scaling for the Fargate worker service based on SQS backlog
*/

locals {
  worker_min_capacity    = 0
  worker_max_capacity    = 5
  scale_target_value     = 5.0
  scale_out_cooldown_sec = 120
  scale_in_cooldown_sec  = 300
}

resource "aws_appautoscaling_target" "worker_target" {
  max_capacity       = local.worker_max_capacity
  min_capacity       = local.worker_min_capacity
  resource_id        = "service/${aws_ecs_cluster.agents_cluster.name}/${aws_ecs_service.worker_service.name}"
  scalable_dimension = "ecs:service:DesiredCount"
  service_namespace  = "ecs"
}

resource "aws_appautoscaling_policy" "sqs_target_tracking" {
  name               = "${var.project_name}-worker-sqs-scaling"
  policy_type        = "TargetTrackingScaling"
  resource_id        = aws_appautoscaling_target.worker_target.resource_id
  scalable_dimension = aws_appautoscaling_target.worker_target.scalable_dimension
  service_namespace  = aws_appautoscaling_target.worker_target.service_namespace

  target_tracking_scaling_policy_configuration {
    target_value       = local.scale_target_value # Scale out if there are more than this # of messages per running task
    scale_out_cooldown = local.scale_out_cooldown_sec
    scale_in_cooldown  = local.scale_in_cooldown_sec

    customized_metric_specification {
      metrics {
        id          = "backlog_per_task"
        expression  = "(m1_visible + m1_inflight) / IF(m2 > 0, m2, 1)"
        label       = "SQS Backlog per Capacity Unit"
        return_data = true
      }
      // Variable m1_visible: messaged waiting to be picked up
      metrics {
        id          = "m1_visible"
        return_data = false
        metric_stat {
          metric {
            namespace   = "AWS/SQS"
            metric_name = "ApproximateNumberOfMessagesVisible" # The standard way SQS metric for how many messages are waiting
            dimensions {
              name  = "QueueName"
              value = aws_sqs_queue.agent_queue.name
            }
          }
          stat = "Average"
        }
      }

      // Variable m1_inflight: messages already picked up by worker but not yet deleted
      metrics {
        id          = "m1_inflight"
        return_data = false
        metric_stat {
          metric {
            namespace   = "AWS/SQS"
            metric_name = "ApproximateNumberOfMessagesNotVisible"
            dimensions {
              name  = "QueueName"
              value = aws_sqs_queue.agent_queue.name
            }
          }
          stat = "Average"
        }
      }

      // Variable m2: ECS running tasks
      metrics {
        id          = "m2"
        return_data = false
        metric_stat {
          metric {
            namespace   = "AWS/ECS"
            metric_name = "RunningTaskCount"
            dimensions {
              name  = "ClusterName"
              value = aws_ecs_cluster.agents_cluster.name
            }
            dimensions {
              name  = "ServiceName"
              value = aws_ecs_service.worker_service.name
            }
          }
          stat = "Average"
        }
      }
    }
  }
}
