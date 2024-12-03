variable "aws_region" {
  default = "eu-central-1"
}

variable "access_key" {
  default = "your_access_key"
}

variable "secret_key" {
  default = "your_secret_key"
}

variable "db_username" {
  default = "admin_username"
}

variable "db_password" {
  default = "Strong_Password"
}

variable "public_key_path" {
  default = "~/.ssh/awspollapp_rsa.pub"
}

variable "private_key_path" {
  default = "~/.ssh/awspollapp_rsa"
}

variable "s3_bucket_name" {
  default = "s3bucketpollapp"
}

variable "sender_email" {
  default = "sender_email@email.com"
}
