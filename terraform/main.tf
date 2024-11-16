# Get Available Availability Zones
data "aws_availability_zones" "available" {
  state = "available"
}

# VPC Creation
resource "aws_vpc" "main" {
  cidr_block = "10.1.0.0/16"

  tags = {
    Name = "main_vpc"
  }
}

# Public Subnets
resource "aws_subnet" "public" {
  count                   = 2
  vpc_id                  = aws_vpc.main.id
  cidr_block              = cidrsubnet(aws_vpc.main.cidr_block, 8, count.index)
  availability_zone       = data.aws_availability_zones.available.names[count.index]
  map_public_ip_on_launch = true

  tags = {
    Name = "public_subnet_${count.index}"
  }
}

# Private Subnets
resource "aws_subnet" "private" {
  count             = 2
  vpc_id            = aws_vpc.main.id
  cidr_block        = cidrsubnet(aws_vpc.main.cidr_block, 8, count.index + 2)
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

# Security Group for ALB
resource "aws_security_group" "alb_sg" {
  name        = "alb_security_group"
  description = "Allow inbound HTTP traffic"
  vpc_id      = aws_vpc.main.id

  ingress {
    description = "HTTP from anywhere"
    from_port   = 80
    to_port     = 80
    protocol    = "tcp"
    cidr_blocks = ["0.0.0.0/0"]
  }

  egress {
    description = "Allow all outbound traffic"
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }

  tags = {
    Name = "alb_security_group"
  }
}

# Security Group for EC2 Instance
resource "aws_security_group" "web_sg" {
  name        = "web_security_group"
  description = "Allow HTTP from ALB and SSH from anywhere"
  vpc_id      = aws_vpc.main.id

  ingress {
    description     = "Allow HTTP from ALB"
    from_port       = 80
    to_port         = 80
    protocol        = "tcp"
    security_groups = [aws_security_group.alb_sg.id]
  }

  ingress {
    description = "Allow SSH"
    from_port   = 22
    to_port     = 22
    protocol    = "tcp"
    cidr_blocks = ["0.0.0.0/0"]  # Replace with your IP for better security
  }

  egress {
    description = "Allow all outbound traffic"
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }

  tags = {
    Name = "web_security_group"
  }
}

# Security Group for RDS Instance
resource "aws_security_group" "rds_sg" {
  name        = "rds_security_group"
  description = "Allow MySQL access from EC2 instances"
  vpc_id      = aws_vpc.main.id

  ingress {
    description     = "Allow MySQL from EC2"
    from_port       = 3306
    to_port         = 3306
    protocol        = "tcp"
    security_groups = [aws_security_group.web_sg.id]
  }

  egress {
    description = "Allow all outbound traffic"
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }

  tags = {
    Name = "rds_security_group"
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
  instance_class         = "db.t3.micro"
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
}

# Key Pair
resource "aws_key_pair" "deployer" {
  key_name   = "deployer_key"
  public_key = file(var.public_key_path)
}

# S3 Bucket
resource "aws_s3_bucket" "app_bucket" {
  bucket = var.s3_bucket_name

  tags = {
    Name = "AppBucket"
  }
}

# IAM Role for EC2 Instance
# IAM Role for EC2 Instance
resource "aws_iam_role" "ec2_role" {
  name = "ec2_role"

  assume_role_policy = jsonencode({
    Version = "2012-10-17",
    Statement = [{
      Effect = "Allow",
      Principal = {
        Service = "ec2.amazonaws.com"
      },
      Action = "sts:AssumeRole"
    }]
  })
}

# IAM Policy for EC2 to Access S3
resource "aws_iam_policy" "ec2_s3_policy" {
  name        = "ec2_s3_policy"
  description = "Policy for EC2 to access S3"
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

# IAM Policy for EC2 to Invoke Lambda
resource "aws_iam_policy" "ec2_lambda_invoke_policy" {
  name        = "ec2_lambda_invoke_policy"
  description = "Policy for EC2 to invoke Lambda functions"
  policy      = jsonencode({
    Version = "2012-10-17",
    Statement = [{
      Action   = "lambda:InvokeFunction",
      Effect   = "Allow",
      Resource = aws_lambda_function.welcome_email.arn
    }]
  })
}

# Attach Policies to EC2 Role
resource "aws_iam_role_policy_attachment" "ec2_s3_policy_attachment" {
  role       = aws_iam_role.ec2_role.name
  policy_arn = aws_iam_policy.ec2_s3_policy.arn
}

resource "aws_iam_role_policy_attachment" "ec2_lambda_invoke_policy_attachment" {
  role       = aws_iam_role.ec2_role.name
  policy_arn = aws_iam_policy.ec2_lambda_invoke_policy.arn
}

# Instance Profile for EC2 Instance
resource "aws_iam_instance_profile" "ec2_instance_profile" {
  name = "ec2_instance_profile"
  role = aws_iam_role.ec2_role.name
}

# EC2 Instance
resource "aws_instance" "app_server" {
  ami                         = "ami-0c351fa00a7272d82"  # Ensure this AMI is correct for your region
  instance_type               = "t3.micro"
  subnet_id                   = aws_subnet.public[0].id
  vpc_security_group_ids      = [aws_security_group.web_sg.id]
  key_name                    = aws_key_pair.deployer.key_name
  associate_public_ip_address = true
  iam_instance_profile        = aws_iam_instance_profile.ec2_instance_profile.name  # Attached IAM Instance Profile

  tags = {
    Name = "AppServer"
  }

  user_data = <<-EOF
    #!/bin/bash
    # Update and install necessary packages
    yum update -y
    yum install -y python3 git mysql unzip

    # Install pip and Python dependencies
    if ! command -v pip3 &> /dev/null; then
      curl -O https://bootstrap.pypa.io/get-pip.py
      python3 get-pip.py
    fi
    pip3 install --upgrade pip
    pip3 install flask pymysql bcrypt gunicorn boto3 flask-session flask-bcrypt python-dotenv

    # Install AWS CLI
    if ! command -v aws &> /dev/null; then
      curl "https://awscli.amazonaws.com/awscli-exe-linux-x86_64.zip" -o "awscliv2.zip"
      unzip awscliv2.zip
      sudo ./aws/install
    fi

    # Clone your application repository
    cd /home/ec2-user
    if [ ! -d "pollAppToAWS" ]; then
      git clone https://github.com/CVTPRN/pollAppToAWS.git
    fi
    cd pollAppToAWS

    # Export environment variables
    export DB_HOST=${aws_db_instance.mysql.address}
    export DB_USER=${var.db_username}
    export DB_PASSWORD=${var.db_password}
    export DB_NAME=mydatabase
    export SECRET_KEY=your_secret_key
    export S3_BUCKET=${aws_s3_bucket.app_bucket.bucket}
    export AWS_DEFAULT_REGION=${var.aws_region}

    # Start the application using Gunicorn
    gunicorn --workers 3 --bind 0.0.0.0:80 app:app &

    echo "Application started successfully."
  EOF
}

# Application Load Balancer (ALB)
resource "aws_lb" "app_lb" {
  name               = "app-load-balancer"
  internal           = false
  load_balancer_type = "application"
  security_groups    = [aws_security_group.alb_sg.id]
  subnets            = [for subnet in aws_subnet.public : subnet.id]

  tags = {
    Name = "AppLoadBalancer"
  }
}

# Target Group
resource "aws_lb_target_group" "app_tg" {
  name     = "app-target-group"
  port     = 80
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
}

# ALB Listener
resource "aws_lb_listener" "http_listener" {
  load_balancer_arn = aws_lb.app_lb.arn
  port              = "80"
  protocol          = "HTTP"

  default_action {
    type             = "forward"
    target_group_arn = aws_lb_target_group.app_tg.arn
  }
}

# Target Group Attachment
resource "aws_lb_target_group_attachment" "app_instance" {
  target_group_arn = aws_lb_target_group.app_tg.arn
  target_id        = aws_instance.app_server.id
  port             = 80
}

# IAM Role for Lambda Function
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

# IAM Policy for Lambda to Send Emails via SES
resource "aws_iam_policy" "lambda_ses_policy" {
  name        = "lambda_ses_policy"
  description = "Policy for Lambda to send emails via SES"
  policy      = jsonencode({
    Version = "2012-10-17",
    Statement = [{
      Action = [
        "ses:SendEmail",
        "ses:SendRawEmail"
      ],
      Effect   = "Allow",
      Resource = "*"
    }]
  })
}

# Attach Policy to Lambda Role
resource "aws_iam_role_policy_attachment" "lambda_role_policy_attachment" {
  role       = aws_iam_role.lambda_role.name
  policy_arn = aws_iam_policy.lambda_ses_policy.arn
}

# Lambda Function
resource "aws_lambda_function" "welcome_email" {
  function_name = "welcome_email_function"
  role          = aws_iam_role.lambda_role.arn
  handler       = "lambda_function.lambda_handler"
  runtime       = "python3.9"  # Update to a supported version
  filename      = "lambda_function.zip"

  # Environment Variables
  environment {
    variables = {
      SENDER_EMAIL = var.sender_email
    }
  }

  depends_on = [aws_iam_role_policy_attachment.lambda_role_policy_attachment]
}

# Output the Load Balancer DNS Name
output "load_balancer_dns_name" {
  value = aws_lb.app_lb.dns_name
}
