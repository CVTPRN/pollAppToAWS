#terraform new version
# main.tf

# Data Sources
data "aws_availability_zones" "available" {
  state = "available"
}

data "aws_caller_identity" "current" {}

# VPC Creation
resource "aws_vpc" "main" {
  cidr_block = "10.0.0.0/16"

  tags = {
    Name = "main_vpc"
  }
}

# Public Subnets
resource "aws_subnet" "public" {
  count             = length(data.aws_availability_zones.available.names)
  vpc_id            = aws_vpc.main.id
  cidr_block        = cidrsubnet(aws_vpc.main.cidr_block, 8, count.index)
  availability_zone = data.aws_availability_zones.available.names[count.index]
  map_public_ip_on_launch = true

  tags = {
    Name = "public_subnet_${count.index}"
  }
}

# Private Subnets
resource "aws_subnet" "private" {
  count             = length(data.aws_availability_zones.available.names)
  vpc_id            = aws_vpc.main.id
  cidr_block        = cidrsubnet(aws_vpc.main.cidr_block, 8, count.index + 10)
  availability_zone = data.aws_availability_zones.available.names[count.index]

  tags = {
    Name = "private_subnet_${count.index}"
  }
}

# Internet Gateway
resource "aws_internet_gateway" "igw" {
  vpc_id = aws_vpc.main.id

  tags = {
    Name = "main_igw"
  }
}

# Public Route Table
resource "aws_route_table" "public" {
  vpc_id = aws_vpc.main.id

  route {
    cidr_block = "0.0.0.0/0"
    gateway_id = aws_internet_gateway.igw.id
  }

  tags = {
    Name = "public_route_table"
  }
}

# Associate Route Table with Public Subnets
resource "aws_route_table_association" "public" {
  count          = length(aws_subnet.public)
  subnet_id      = aws_subnet.public[count.index].id
  route_table_id = aws_route_table.public.id
}

# Allocate Elastic IPs for NAT Gateways (1 per AZ)
resource "aws_eip" "nat" {
  count  = length(data.aws_availability_zones.available.names)
  domain = "vpc"  # Helyesen használjuk a 'domain' attribútumot
  
  tags = {
    Name = "nat_eip_${count.index}"
  }
}

# Create NAT Gateways (1 per AZ)
resource "aws_nat_gateway" "nat" {
  count         = length(data.aws_availability_zones.available.names)
  allocation_id = aws_eip.nat[count.index].id
  subnet_id     = aws_subnet.public[count.index].id

  tags = {
    Name = "nat_gw_${count.index}"
  }

  depends_on = [aws_internet_gateway.igw]
}

# Private Route Tables
resource "aws_route_table" "private" {
  count  = length(aws_subnet.private)
  vpc_id = aws_vpc.main.id

  route {
    cidr_block     = "0.0.0.0/0"
    nat_gateway_id = aws_nat_gateway.nat[count.index].id
  }

  tags = {
    Name = "private_route_table_${count.index}"
  }
}

# Associate Route Table with Private Subnets
resource "aws_route_table_association" "private" {
  count          = length(aws_subnet.private)
  subnet_id      = aws_subnet.private[count.index].id
  route_table_id = aws_route_table.private[count.index].id
}

# Security Groups

resource "aws_security_group" "alb_sg" {
  name        = "alb_security_group"
  description = "Allow HTTP inbound traffic"
  vpc_id      = aws_vpc.main.id

  ingress {
    description = "HTTP"
    from_port   = 80
    to_port     = 80
    protocol    = "tcp"
    cidr_blocks = ["0.0.0.0/0"]
  }

  egress {
    description = "All outbound"
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }

  tags = {
    Name = "alb_security_group"
  }
}



# EC2 Security Group
resource "aws_security_group" "ec2_sg" {
  name        = "ec2_security_group"
  description = "Allow HTTP from ALB and SSH from trusted IP"
  vpc_id      = aws_vpc.main.id

  ingress {
    description = "SSH from trusted IP"
    from_port   = 22
    to_port     = 22
    protocol    = "tcp"
    cidr_blocks = ["0.0.0.0/0"]
  }

  ingress {
    description     = "HTTP from ALB"
    from_port       = 5000
    to_port         = 5000
    protocol        = "tcp"
    security_groups = [aws_security_group.alb_sg.id]
  }

  egress {
    description = "All outbound"
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }

  tags = {
    Name = "ec2_security_group"
  }
}

# RDS Security Group
resource "aws_security_group" "rds_sg" {
  name        = "rds_security_group"
  description = "Allow MySQL access from EC2 instances"
  vpc_id      = aws_vpc.main.id

  ingress {
    description     = "MySQL from EC2"
    from_port       = 3306
    to_port         = 3306
    protocol        = "tcp"
    security_groups = [aws_security_group.ec2_sg.id]
  }

  egress {
    description = "All outbound"
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }

  tags = {
    Name = "rds_security_group"
  }
}

# S3 Bucket
resource "aws_s3_bucket" "app_bucket" {
  bucket = var.s3_bucket_name

  tags = {
    Name = "AppBucket"
  }
}

# RDS Subnet Group
resource "aws_db_subnet_group" "default" {
  name       = "main_subnet_group"
  subnet_ids = [for subnet in aws_subnet.private : subnet.id]

  tags = {
    Name = "Main subnet group"
  }
}

# RDS Instance
resource "aws_db_instance" "mysql" {
  allocated_storage      = 20
  engine                 = "mysql"
  engine_version         = "8.0"
  instance_class         = "db.t3.micro" # Frissítve a Multi-AZ támogatáshoz
  db_name                = "mydatabase"
  username               = var.db_username
  password               = var.db_password
  parameter_group_name   = "default.mysql8.0"
  skip_final_snapshot    = true
  vpc_security_group_ids = [aws_security_group.rds_sg.id]
  db_subnet_group_name   = aws_db_subnet_group.default.name
  publicly_accessible    = false

  tags = {
    Name = "MySQL RDS Instance"
  }

  multi_az = true
}

# IAM Role for EC2 to Access S3 and SSM Parameters
resource "aws_iam_role" "ec2_role" {
  name = "ec2_role"

  assume_role_policy = jsonencode({
    Version = "2012-10-17",
    Statement = [{
      Action    = "sts:AssumeRole",
      Effect    = "Allow",
      Principal = {
        Service = "ec2.amazonaws.com"
      }
    }]
  })
}

# IAM Policy for S3 Access
resource "aws_iam_policy" "s3_policy" {
  name        = "s3_policy"
  description = "Policy for EC2 instances to access S3"
  policy      = jsonencode({
    Version = "2012-10-17",
    Statement = [{
      Action = [
        "s3:PutObject",
        "s3:GetObject",
        "s3:DeleteObject",
        "s3:ListBucket"
      ],
      Effect   = "Allow",
      Resource = [
        aws_s3_bucket.app_bucket.arn,
        "${aws_s3_bucket.app_bucket.arn}/*"
      ]
    }]
  })
}

# IAM Policy for SSM Parameter Store Access
resource "aws_iam_policy" "ssm_policy" {
  name        = "ssm_policy"
  description = "Policy for EC2 instances to access SSM Parameters"
  policy      = jsonencode({
    Version = "2012-10-17",
    Statement = [
      {
        Effect   = "Allow",
        Action   = [
          "ssm:GetParameter",
          "ssm:GetParameters"
        ],
        Resource = [
          "arn:aws:ssm:${var.aws_region}:${data.aws_caller_identity.current.account_id}:parameter/pollApp/*"
        ]
      }
    ]
  })
}

# Attach S3 Policy to EC2 Role
resource "aws_iam_role_policy_attachment" "ec2_s3_policy_attachment" {
  role       = aws_iam_role.ec2_role.name
  policy_arn = aws_iam_policy.s3_policy.arn
}

# Attach SSM Policy to EC2 Role
resource "aws_iam_role_policy_attachment" "ec2_ssm_policy_attachment" {
  role       = aws_iam_role.ec2_role.name
  policy_arn = aws_iam_policy.ssm_policy.arn
}

# Instance Profile
resource "aws_iam_instance_profile" "ec2_instance_profile" {
  name = "ec2_instance_profile"
  role = aws_iam_role.ec2_role.name
}

# Key Pair
resource "aws_key_pair" "deployer" {
  key_name   = "deployer_key"
  public_key = file(var.public_key_path)
}

# SSM Parameters for Secrets

# DB Password
resource "aws_ssm_parameter" "db_password" {
  name  = "/pollApp/db_password"
  type  = "SecureString"
  value = var.db_password

  tags = {
    Name = "DB Password"
  }
}

# SECRET_KEY for Flask
resource "aws_ssm_parameter" "secret_key" {
  name  = "/pollApp/secret_key"
  type  = "SecureString"
  value = "AKIARHQBNDNVZD4DPXEU"

  tags = {
    Name = "Flask Secret Key"
  }
}

resource "aws_instance" "app_server" {
  ami                         = "ami-0c351fa00a7272d82"  # Ensure this AMI is correct for your region
  instance_type               = "t3.micro"
  subnet_id                   = aws_subnet.public[0].id
  vpc_security_group_ids      = [aws_security_group.ec2_sg.id]
  key_name                    = aws_key_pair.deployer.key_name
  associate_public_ip_address = true
  iam_instance_profile        = aws_iam_instance_profile.ec2_instance_profile.name

  tags = {
    Name = "AppServer"
  }

  user_data = <<-EOF
    #!/bin/bash
    set -e

    LOGFILE="/var/log/user_data.log"
    exec > >(tee -a $$LOGFILE) 2>&1

    echo "Starting user_data script execution..."

    # Update and install necessary packages
    yum update -y
    yum install -y python3 git mysql unzip

    # Install pip and Python dependencies
    if ! command -v pip3 &> /dev/null
    then
        curl -O https://bootstrap.pypa.io/get-pip.py
        python3 get-pip.py
    fi
    pip3 install --upgrade pip
    pip3 install flask pymysql bcrypt gunicorn boto3 flask-session flask-bcrypt python-dotenv

    # Clone your application repository
    cd /home/ec2-user
    if [ ! -d "pollAppToAWS" ]; then
        git clone https://github.com/CVTPRN/pollAppToAWS.git pollAppToAWS
    else
        echo "Repository already cloned."
        cd pollAppToAWS
        git pull origin main
    fi
    cd pollAppToAWS

    # Fetch parameters from SSM (if applicable)
    # Uncomment and modify if using SSM Parameter Store
    # DB_PASSWORD=$(aws ssm get-parameter --name "/pollApp/db_password" --with-decryption --query "Parameter.Value" --output text)
    # SECRET_KEY=$(aws ssm get-parameter --name "/pollApp/secret_key" --with-decryption --query "Parameter.Value" --output text)

    # Export environment variables
    export DB_HOST=${aws_db_instance.mysql.endpoint}
    export DB_USER=${var.db_username}
    export DB_PASSWORD=${var.db_password}
    export DB_NAME=mydatabase
    export SECRET_KEY=9W6msLr7EnHieLDuxAFj6gqzAmQXHJGADqwQ7e/e
    export S3_BUCKET=${aws_s3_bucket.app_bucket.bucket}
    export AWS_DEFAULT_REGION=${var.aws_region}

    # Create a systemd service file for Gunicorn
    cat <<SYSTEMD_EOF > /etc/systemd/system/flask_app.service
    [Unit]
    Description=Gunicorn instance to serve Flask App
    After=network.target

    [Service]
    User=ec2-user
    Group=nginx
    WorkingDirectory=/home/ec2-user/pollAppToAWS
    Environment="DB_HOST=${aws_db_instance.mysql.endpoint}"
    Environment="DB_USER=${var.db_username}"
    Environment="DB_PASSWORD=${var.db_password}"
    Environment="DB_NAME=mydatabase"
    Environment="SECRET_KEY=9W6msLr7EnHieLDuxAFj6gqzAmQXHJGADqwQ7e/e"
    Environment="S3_BUCKET=${aws_s3_bucket.app_bucket.bucket}"
    Environment="AWS_DEFAULT_REGION=${var.aws_region}"
    ExecStart=/usr/local/bin/gunicorn --workers 3 --bind 0.0.0.0:5000 app:app

    [Install]
    WantedBy=multi-user.target
    SYSTEMD_EOF

    # Reload systemd to recognize the new service
    systemctl daemon-reload

    # Start and enable the Flask app service
    systemctl start flask_app
    systemctl enable flask_app

    echo "user_data script execution completed."
  EOF
}



# Route53 Hosted Zone
resource "aws_route53_zone" "main" {
  name = "regomeszaros.com"
}

# Application Load Balancer (ALB) with HTTPS
resource "aws_lb" "app_lb" {
  name               = "app-load-balancer"
  internal           = false
  load_balancer_type = "application"
  security_groups    = [aws_security_group.alb_sg.id]
  subnets            = [for subnet in aws_subnet.public : subnet.id]

  enable_deletion_protection = false

  tags = {
    Name = "AppLoadBalancer"
  }
}

# ALB Listener for HTTP
resource "aws_lb_listener" "http_listener" {
  load_balancer_arn = aws_lb.app_lb.arn
  port              = "80"
  protocol          = "HTTP"

  default_action {
    type             = "forward"
    target_group_arn = aws_lb_target_group.app_tg.arn
  }
}


# Target Group
resource "aws_lb_target_group" "app_tg" {
  name     = "app-target-group"
  port     = 5000
  protocol = "HTTP"
  vpc_id   = aws_vpc.main.id

  health_check {
    path                = "/health"
    protocol            = "HTTP"
    matcher             = "200-399"
    interval            = 30
    timeout             = 5
    unhealthy_threshold = 2
    healthy_threshold   = 2
  }

  tags = {
    Name = "AppTargetGroup"
  }

  lifecycle {
    create_before_destroy = true
  }
}

# Target Group Attachment
resource "aws_lb_target_group_attachment" "app_instance" {
  target_group_arn = aws_lb_target_group.app_tg.arn
  target_id        = aws_instance.app_server.id
  port             = 5000
}

# S3 Bucket IAM Role and Policies (Already Defined Above)

# API Gateway

# REST API
resource "aws_api_gateway_rest_api" "app_api" {
  name = "app-api"

  tags = {
    Name = "AppAPI"
  }
}

# Root Method
resource "aws_api_gateway_method" "root_method" {
  rest_api_id   = aws_api_gateway_rest_api.app_api.id
  resource_id   = aws_api_gateway_rest_api.app_api.root_resource_id
  http_method   = "ANY"
  authorization = "NONE"
}

# Root Integration
resource "aws_api_gateway_integration" "root_integration" {
  rest_api_id             = aws_api_gateway_rest_api.app_api.id
  resource_id             = aws_api_gateway_rest_api.app_api.root_resource_id
  http_method             = aws_api_gateway_method.root_method.http_method
  type                    = "HTTP_PROXY"
  integration_http_method = "ANY"
  uri                     = "http://${aws_lb.app_lb.dns_name}/"

  depends_on = [aws_api_gateway_method.root_method]
}

# Proxy Resource
resource "aws_api_gateway_resource" "proxy" {
  rest_api_id = aws_api_gateway_rest_api.app_api.id
  parent_id   = aws_api_gateway_rest_api.app_api.root_resource_id
  path_part   = "{proxy+}"
}

# Proxy Method
resource "aws_api_gateway_method" "proxy_method" {
  rest_api_id   = aws_api_gateway_rest_api.app_api.id
  resource_id   = aws_api_gateway_resource.proxy.id
  http_method   = "ANY"
  authorization = "NONE"
}

# Proxy Integration
resource "aws_api_gateway_integration" "proxy_integration" {
  rest_api_id             = aws_api_gateway_rest_api.app_api.id
  resource_id             = aws_api_gateway_resource.proxy.id
  http_method             = aws_api_gateway_method.proxy_method.http_method
  type                    = "HTTP_PROXY"
  integration_http_method = "ANY"
  uri                     = "http://${aws_lb.app_lb.dns_name}/$proxy"

  depends_on = [aws_api_gateway_method.proxy_method]
}

# API Deployment
resource "aws_api_gateway_deployment" "app_deployment" {
  depends_on = [
    aws_api_gateway_integration.root_integration,
    aws_api_gateway_integration.proxy_integration,
    aws_api_gateway_method.root_method,
    aws_api_gateway_method.proxy_method
  ]

  rest_api_id = aws_api_gateway_rest_api.app_api.id
  stage_name  = "prod"
}

# Route 53 A Record for Root Domain
resource "aws_route53_record" "app_domain" {
  zone_id = aws_route53_zone.main.zone_id
  name    = "regomeszaros.com"
  type    = "A"

  alias {
    name                   = aws_lb.app_lb.dns_name
    zone_id                = aws_lb.app_lb.zone_id
    evaluate_target_health = true
  }
}

# IAM Role for Lambda
resource "aws_iam_role" "lambda_role" {
  name = "lambda_ses_role"

  assume_role_policy = jsonencode({
    Version = "2012-10-17",
    Statement = [{
      Action    = "sts:AssumeRole",
      Effect    = "Allow",
      Principal = {
        Service = "lambda.amazonaws.com"
      }
    }]
  })
}

# IAM Policy for SES Access (Restrict to specific SES resources)
resource "aws_iam_policy" "lambda_ses_policy" {
  name        = "lambda_ses_policy"
  description = "Policy for Lambda to send emails via SES"
  policy      = jsonencode({
    Version = "2012-10-17",
    Statement = [{
      Action   = [
        "ses:SendEmail",
        "ses:SendRawEmail"
      ],
      Effect   = "Allow",
      Resource = "arn:aws:ses:${var.aws_region}:${data.aws_caller_identity.current.account_id}:identity/*"
    }]
  })
}

# Attach SES Policy to Lambda Role
resource "aws_iam_role_policy_attachment" "lambda_role_policy_attachment" {
  role       = aws_iam_role.lambda_role.name
  policy_arn = aws_iam_policy.lambda_ses_policy.arn
}

# Lambda Function
resource "aws_lambda_function" "welcome_email" {
  function_name = "welcome_email_function"
  role          = aws_iam_role.lambda_role.arn
  handler       = "lambda_function.lambda_handler"
  runtime       = "python3.8"
  filename      = "lambda_function.zip"  # Biztosítsd, hogy ez a fájl elérhető és megfelelően csomagolt

  # Environment Variables
  environment {
    variables = {
      SENDER_EMAIL = var.sender_email
    }
  }

  depends_on = [aws_iam_role_policy_attachment.lambda_role_policy_attachment]
}

# IAM Policy for EC2 to Invoke Lambda
resource "aws_iam_policy" "ec2_invoke_lambda_policy" {
  name        = "ec2_invoke_lambda_policy"
  description = "Policy for EC2 to invoke Lambda functions"
  policy      = jsonencode({
    Version = "2012-10-17",
    Statement = [{
      Action   = ["lambda:InvokeFunction"],
      Effect   = "Allow",
      Resource = aws_lambda_function.welcome_email.arn
    }]
  })
}

# Attach the Policy to the EC2 Role
resource "aws_iam_role_policy_attachment" "ec2_invoke_lambda_policy_attachment" {
  role       = aws_iam_role.ec2_role.name
  policy_arn = aws_iam_policy.ec2_invoke_lambda_policy.arn
}
