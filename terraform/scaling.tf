/* 
  Application Auto Scaling (High-Resolution Multi-Step Scaling)

  Contents:
  - Scaling Bounds: Manages the Fargate worker capacity (0 to 5 tasks).
  - Multi-Step Scale-Up Policy: Dynamically provisions capacity based on the volume of traffic spikes. 
    Cooldown is tuned to Fargate's real cold-start time (not lower), so the policy doesn't re-evaluate and over-provision before
    the first new task has actually started consuming messages.
  - Linear Scale-Down Policy: Gracefully scales down 1 task at a time to drain trailing data.
*/

locals {
  worker_min_capacity = 0
  worker_max_capacity = 5
}

// Scalable Target 

resource "aws_appautoscaling_target" "worker_target" {
  max_capacity       = local.worker_max_capacity
  min_capacity       = local.worker_min_capacity
  resource_id        = "service/${aws_ecs_cluster.agents_cluster.name}/${aws_ecs_service.worker_service.name}"
  scalable_dimension = "ecs:service:DesiredCount"
  service_namespace  = "ecs"
}

// Multi-Step Scale-Up Policy 

resource "aws_appautoscaling_policy" "worker_scale_up" {
  name               = "${var.project_name}-worker-scale-up"
  policy_type        = "StepScaling"
  resource_id        = aws_appautoscaling_target.worker_target.resource_id
  scalable_dimension = aws_appautoscaling_target.worker_target.scalable_dimension
  service_namespace  = aws_appautoscaling_target.worker_target.service_namespace

  step_scaling_policy_configuration {
    adjustment_type         = "ChangeInCapacity"
    cooldown                = 90
    metric_aggregation_type = "Maximum"

    // Light load (1 to 11 messages), i.e 0-10 above the alarm threshold -> Add 1 worker task 
    step_adjustment {
      metric_interval_lower_bound = 0
      metric_interval_upper_bound = 10
      scaling_adjustment          = 1
    }

    // Moderate spike (11 to 51 messages) -> Add 3 worker tasks immediately
    step_adjustment {
      metric_interval_lower_bound = 10
      metric_interval_upper_bound = 50
      scaling_adjustment          = 3
    }

    // Mass flood (51+ messages) -> Immediately spin up max capacity (5 tasks)
    step_adjustment {
      metric_interval_lower_bound = 50
      scaling_adjustment          = 5
    }
  }
}

// Scale-Down Policy 

resource "aws_appautoscaling_policy" "worker_scale_down" {
  name               = "${var.project_name}-worker-scale-down"
  policy_type        = "StepScaling"
  resource_id        = aws_appautoscaling_target.worker_target.resource_id
  scalable_dimension = aws_appautoscaling_target.worker_target.scalable_dimension
  service_namespace  = aws_appautoscaling_target.worker_target.service_namespace

  step_scaling_policy_configuration {
    adjustment_type         = "ChangeInCapacity"
    cooldown                = 120
    metric_aggregation_type = "Maximum"

    step_adjustment {
      metric_interval_upper_bound = 0
      scaling_adjustment          = -1
    }
  }
}
