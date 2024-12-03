import os
import json
import ipaddress
import pulumi
import pulumi_aws as aws

config = pulumi.Config()

# Variables
aws_region = config.get("aws_region") or "eu-central-1"
db_username = config.get("db_username") or "admin"
db_password = config.get_secret("db_password") or pulumi.Output.secret("Strong_password")
public_key_path = config.get("public_key_path") or "~/.ssh/awspollapp_rsa.pub"
s3_bucket_name = config.get("s3_bucket_name") or "s3bucketpollapp"
sender_email = config.get("sender_email") or "x@gmail.com"
access_key = config.get_secret("access_key") or pulumi.Output.secret("X")
secret_key = config.get_secret("secret_key") or pulumi.Output.secret("X")

# Provider Configuration
aws_provider = aws.Provider("aws_provider",
    region=aws_region,
    access_key=access_key,
    secret_key=secret_key
)

# Data Source: AWS Availability Zones
available_zones = aws.get_availability_zones(state="available")

# Helper function for CIDR subnet calculation
def cidr_subnet(supernet_cidr, newbits, netnum):
    supernet = ipaddress.ip_network(supernet_cidr)
    subnets = list(supernet.subnets(new_prefix=supernet.prefixlen + newbits))
    return str(subnets[netnum])

# VPC Creation
main_vpc = aws.ec2.Vpc("main_vpc",
    cidr_block="10.1.0.0/16",
    tags={"Name": "main_vpc"},
    opts=pulumi.ResourceOptions(provider=aws_provider)
)

# Public Subnets
public_subnets = []
for i in range(2):
    subnet = aws.ec2.Subnet(f"public_subnet_{i}",
        vpc_id=main_vpc.id,
        cidr_block=main_vpc.cidr_block.apply(lambda cidr: cidr_subnet(cidr, 8, i)),
        availability_zone=available_zones.names[i],
        map_public_ip_on_launch=True,
        tags={"Name": f"public_subnet_{i}"},
        opts=pulumi.ResourceOptions(provider=aws_provider)
    )
    public_subnets.append(subnet)

# Private Subnets
private_subnets = []
for i in range(2):
    subnet = aws.ec2.Subnet(f"private_subnet_{i}",
        vpc_id=main_vpc.id,
        cidr_block=main_vpc.cidr_block.apply(lambda cidr: cidr_subnet(cidr, 8, i + 2)),
        availability_zone=available_zones.names[i],
        tags={"Name": f"private_subnet_{i}"},
        opts=pulumi.ResourceOptions(provider=aws_provider)
    )
    private_subnets.append(subnet)

# Internet Gateway
igw = aws.ec2.InternetGateway("main_igw",
    vpc_id=main_vpc.id,
    tags={"Name": "main_igw"},
    opts=pulumi.ResourceOptions(provider=aws_provider)
)

# Public Route Table
public_route_table = aws.ec2.RouteTable("public_route_table",
    vpc_id=main_vpc.id,
    routes=[aws.ec2.RouteTableRouteArgs(
        cidr_block="0.0.0.0/0",
        gateway_id=igw.id
    )],
    tags={"Name": "public_route_table"},
    opts=pulumi.ResourceOptions(provider=aws_provider)
)

# Associate Route Table with Public Subnets
for i, subnet in enumerate(public_subnets):
    aws.ec2.RouteTableAssociation(f"public_rt_assoc_{i}",
        subnet_id=subnet.id,
        route_table_id=public_route_table.id,
        opts=pulumi.ResourceOptions(provider=aws_provider)
    )

# Security Groups
alb_sg = aws.ec2.SecurityGroup("alb_security_group",
    description="Allow inbound HTTP traffic",
    vpc_id=main_vpc.id,
    ingress=[aws.ec2.SecurityGroupIngressArgs(
        description="HTTP from anywhere",
        from_port=80,
        to_port=80,
        protocol="tcp",
        cidr_blocks=["0.0.0.0/0"]
    )],
    egress=[aws.ec2.SecurityGroupEgressArgs(
        description="Allow all outbound traffic",
        from_port=0,
        to_port=0,
        protocol="-1",
        cidr_blocks=["0.0.0.0/0"]
    )],
    tags={"Name": "alb_security_group"},
    opts=pulumi.ResourceOptions(provider=aws_provider)
)

web_sg = aws.ec2.SecurityGroup("web_security_group",
    description="Allow HTTP from ALB and SSH from anywhere",
    vpc_id=main_vpc.id,
    ingress=[
        aws.ec2.SecurityGroupIngressArgs(
            description="Allow HTTP from ALB",
            from_port=80,
            to_port=80,
            protocol="tcp",
            security_groups=[alb_sg.id]
        ),
        aws.ec2.SecurityGroupIngressArgs(
            description="Allow SSH",
            from_port=22,
            to_port=22,
            protocol="tcp",
            cidr_blocks=["0.0.0.0/0"]
        )
    ],
    egress=[aws.ec2.SecurityGroupEgressArgs(
        description="Allow all outbound traffic",
        from_port=0,
        to_port=0,
        protocol="-1",
        cidr_blocks=["0.0.0.0/0"]
    )],
    tags={"Name": "web_security_group"},
    opts=pulumi.ResourceOptions(provider=aws_provider)
)

rds_sg = aws.ec2.SecurityGroup("rds_security_group",
    description="Allow MySQL access from EC2 instances",
    vpc_id=main_vpc.id,
    ingress=[aws.ec2.SecurityGroupIngressArgs(
        description="Allow MySQL from EC2",
        from_port=3306,
        to_port=3306,
        protocol="tcp",
        security_groups=[web_sg.id]
    )],
    egress=[aws.ec2.SecurityGroupEgressArgs(
        description="Allow all outbound traffic",
        from_port=0,
        to_port=0,
        protocol="-1",
        cidr_blocks=["0.0.0.0/0"]
    )],
    tags={"Name": "rds_security_group"},
    opts=pulumi.ResourceOptions(provider=aws_provider)
)

# RDS Subnet Group
db_subnet_group = aws.rds.SubnetGroup("main_subnet_group",
    subnet_ids=[subnet.id for subnet in private_subnets],
    tags={"Name": "Main subnet group"},
    opts=pulumi.ResourceOptions(provider=aws_provider)
)

# RDS Instance
rds_instance = aws.rds.Instance("mysql",
    allocated_storage=20,
    engine="mysql",
    engine_version="8.0",
    instance_class="db.t3.micro",
    name="mydatabase",
    username=db_username,
    password=db_password,
    parameter_group_name="default.mysql8.0",
    skip_final_snapshot=True,
    vpc_security_group_ids=[rds_sg.id],
    db_subnet_group_name=db_subnet_group.name,
    publicly_accessible=False,
    tags={"Name": "MySQL RDS Instance"},
    opts=pulumi.ResourceOptions(provider=aws_provider)
)

# Key Pair
public_key_path_expanded = os.path.expanduser(public_key_path)
with open(public_key_path_expanded, 'r') as f:
    public_key = f.read()

key_pair = aws.ec2.KeyPair("deployer_key",
    key_name="deployer_key",
    public_key=public_key,
    opts=pulumi.ResourceOptions(provider=aws_provider)
)

# S3 Bucket
app_bucket = aws.s3.Bucket("app_bucket",
    bucket=s3_bucket_name,
    tags={"Name": "AppBucket"},
    opts=pulumi.ResourceOptions(provider=aws_provider)
)

# IAM Roles and Policies for EC2
ec2_role = aws.iam.Role("ec2_role",
    name="ec2_role",
    assume_role_policy=json.dumps({
        "Version": "2012-10-17",
        "Statement": [{
            "Effect": "Allow",
            "Principal": {"Service": "ec2.amazonaws.com"},
            "Action": "sts:AssumeRole"
        }]
    })
)

ec2_s3_policy = app_bucket.arn.apply(lambda bucket_arn: aws.iam.Policy("ec2_s3_policy",
    name="ec2_s3_policy",
    description="Policy for EC2 to access S3",
    policy=json.dumps({
        "Version": "2012-10-17",
        "Statement": [{
            "Effect": "Allow",
            "Action": [
                "s3:PutObject",
                "s3:GetObject",
                "s3:DeleteObject",
                "s3:ListBucket"
            ],
            "Resource": [
                bucket_arn,
                f"{bucket_arn}/*"
            ]
        }]
    })
))

# Lambda Functions (defined later) will be needed here

# Attach Policies to EC2 Role
ec2_s3_policy_attachment = ec2_s3_policy.apply(lambda policy: aws.iam.RolePolicyAttachment("ec2_s3_policy_attachment",
    role=ec2_role.name,
    policy_arn=policy.arn
))

# Instance Profile for EC2 Instance
ec2_instance_profile = aws.iam.InstanceProfile("ec2_instance_profile",
    name="ec2_instance_profile",
    role=ec2_role.name
)

# EC2 Instance User Data
def create_user_data(db_host, s3_bucket_name):
    return f"""#!/bin/bash
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
export DB_HOST={db_host}
export DB_USER={db_username}
export DB_PASSWORD={db_password}
export DB_NAME=mydatabase
export SECRET_KEY=your_secret_key
export S3_BUCKET={s3_bucket_name}
export AWS_DEFAULT_REGION={aws_region}

# Start the application using Gunicorn
gunicorn --workers 3 --bind 0.0.0.0:80 app:app &

echo "Application started successfully."
"""

user_data = pulumi.Output.all(rds_instance.address, app_bucket.bucket).apply(
    lambda args: create_user_data(*args)
)

# EC2 Instance
app_server = aws.ec2.Instance("app_server",
    ami="ami-0c351fa00a7272d82",
    instance_type="t3.micro",
    subnet_id=public_subnets[0].id,
    vpc_security_group_ids=[web_sg.id],
    key_name=key_pair.key_name,
    associate_public_ip_address=True,
    iam_instance_profile=ec2_instance_profile.name,
    user_data=user_data,
    tags={"Name": "AppServer"},
    opts=pulumi.ResourceOptions(provider=aws_provider)
)

# Load Balancer and Target Groups
app_lb = aws.lb.LoadBalancer("app_load_balancer",
    name="app-load-balancer",
    internal=False,
    load_balancer_type="application",
    security_groups=[alb_sg.id],
    subnets=[subnet.id for subnet in public_subnets],
    tags={"Name": "AppLoadBalancer"},
    opts=pulumi.ResourceOptions(provider=aws_provider)
)

app_tg = aws.lb.TargetGroup("app_target_group",
    name="app-target-group",
    port=80,
    protocol="HTTP",
    vpc_id=main_vpc.id,
    health_check=aws.lb.TargetGroupHealthCheckArgs(
        path="/health",
        protocol="HTTP",
        matcher="200-399",
        interval=30,
        timeout=5,
        unhealthy_threshold=2,
        healthy_threshold=2
    ),
    tags={"Name": "AppTargetGroup"},
    opts=pulumi.ResourceOptions(provider=aws_provider)
)

http_listener = aws.lb.Listener("http_listener",
    load_balancer_arn=app_lb.arn,
    port="80",
    protocol="HTTP",
    default_actions=[aws.lb.ListenerDefaultActionArgs(
        type="forward",
        target_group_arn=app_tg.arn
    )],
    opts=pulumi.ResourceOptions(provider=aws_provider)
)

app_instance_attachment = aws.lb.TargetGroupAttachment("app_instance",
    target_group_arn=app_tg.arn,
    target_id=app_server.id,
    port=80,
    opts=pulumi.ResourceOptions(provider=aws_provider)
)

# IAM Roles and Policies for Lambda Functions
lambda_role = aws.iam.Role("lambda_role",
    name="lambda_role",
    assume_role_policy=json.dumps({
        "Version": "2012-10-17",
        "Statement": [{
            "Effect": "Allow",
            "Principal": {"Service": "lambda.amazonaws.com"},
            "Action": "sts:AssumeRole"
        }]
    })
)

lambda_ses_policy = aws.iam.Policy("lambda_ses_policy",
    name="lambda_ses_policy",
    description="Policy for Lambda to send emails via SES",
    policy=json.dumps({
        "Version": "2012-10-17",
        "Statement": [{
            "Effect": "Allow",
            "Action": [
                "ses:SendEmail",
                "ses:SendRawEmail"
            ],
            "Resource": "*"
        }]
    })
)

lambda_s3_policy = app_bucket.arn.apply(lambda bucket_arn: aws.iam.Policy("lambda_s3_policy",
    name="lambda_s3_policy",
    description="Policy for Lambda to access S3 bucket",
    policy=json.dumps({
        "Version": "2012-10-17",
        "Statement": [{
            "Effect": "Allow",
            "Action": [
                "s3:GetObject",
                "s3:PutObject",
                "s3:DeleteObject",
                "s3:ListBucket"
            ],
            "Resource": [
                bucket_arn,
                f"{bucket_arn}/*"
            ]
        }]
    })
))

lambda_ses_policy_attachment = aws.iam.RolePolicyAttachment("lambda_ses_policy_attachment",
    role=lambda_role.name,
    policy_arn=lambda_ses_policy.arn
)

lambda_s3_policy_attachment = lambda_s3_policy.apply(lambda policy: aws.iam.RolePolicyAttachment("lambda_s3_policy_attachment",
    role=lambda_role.name,
    policy_arn=policy.arn
))

lambda_basic_execution = aws.iam.RolePolicyAttachment("lambda_basic_execution",
    role=lambda_role.name,
    policy_arn="arn:aws:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole"
)

# Lambda Functions
welcome_email_function = aws.lambda_.Function("welcome_email_function",
    function_name="welcome_email_function",
    role=lambda_role.arn,
    handler="lambda_function.lambda_handler",
    runtime="python3.9",
    code=pulumi.FileArchive("lambda_function.zip"),
    environment=aws.lambda_.FunctionEnvironmentArgs(
        variables={"SENDER_EMAIL": sender_email}
    ),
    opts=pulumi.ResourceOptions(
        depends_on=[lambda_ses_policy_attachment, lambda_basic_execution]
    )
)

csv_handler_function = aws.lambda_.Function("csv_handler_function",
    function_name="csv_handler_function",
    role=lambda_role.arn,
    handler="lambda_function.lambda_handler",
    runtime="python3.9",
    code=pulumi.FileArchive("lambda_function2.zip"),
    environment=aws.lambda_.FunctionEnvironmentArgs(
        variables={"S3_BUCKET": app_bucket.bucket}
    ),
    opts=pulumi.ResourceOptions(
        depends_on=[lambda_s3_policy_attachment, lambda_basic_execution]
    )
)

# IAM Policy for EC2 to Invoke Lambda
ec2_lambda_invoke_policy = pulumi.Output.all(
    welcome_email_function.arn, csv_handler_function.arn
).apply(lambda arns: aws.iam.Policy("ec2_lambda_invoke_policy",
    name="ec2_lambda_invoke_policy",
    description="Policy for EC2 to invoke Lambda functions",
    policy=json.dumps({
        "Version": "2012-10-17",
        "Statement": [{
            "Effect": "Allow",
            "Action": "lambda:InvokeFunction",
            "Resource": arns
        }]
    })
))

# Attach the Lambda Invoke Policy to EC2 Role
ec2_lambda_invoke_policy_attachment = ec2_lambda_invoke_policy.apply(lambda policy: aws.iam.RolePolicyAttachment("ec2_lambda_invoke_policy_attachment",
    role=ec2_role.name,
    policy_arn=policy.arn
))

# Output the Load Balancer DNS Name
pulumi.export("load_balancer_dns_name", app_lb.dns_name)
