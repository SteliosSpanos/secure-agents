/*
    Auto scaling for the Fargate worker service based on SQS backlog
*/

resource "aws_appautoscaling_target" "worker_target" {
  max_capacity       = 5
  min_capacity       = 0
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
    target_value       = 10.0 # Scale out if there are more than 10 messages per running task
    scale_out_cooldown = 60
    scale_in_cooldown  = 300

    customized_metric_specification {
      metrics {
        id          = "backlog_per_task"
        expression  = "m1 / MAX(m2, 1)"
        label       = "SQS Backlog per Capacity Unit"
        return_data = true
      }
      // Variable m1: SQS queue depth
      metrics {
        id = "m1"
        metric_stat {
          metric {
            namespace   = "AWS/SQS"
            metric_name = "ApproximateNumberOfMessagesVisible" # The standard way SQS metric for how many messages are waiting
            dimensions {
              name  = "QueueName"
              value = aws_sqs_queue.agent_queue.name
            }
          }
          stat = "Sum"
        }
        return_data = false
      }

      // Variable m2: ECS running tasks
      metrics {
        id = "m2"
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
        return_data = false
      }
    }
  }
}
