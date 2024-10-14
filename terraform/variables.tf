variable "aws_region" {
  default = "eu-central-1"
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
