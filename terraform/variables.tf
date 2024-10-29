variable "aws_region" {
  default = "eu-central-1"
}

variable "access_key" {
  default = "X"
}

variable "secret_key" {
  default = "X"
}

variable "db_username" {
  default = "admin"
}

variable "db_password" {
  default = "N3lopjad!"
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
  default = "meszaros@regomeszaros.com"
}
