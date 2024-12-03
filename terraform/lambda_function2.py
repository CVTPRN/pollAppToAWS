import os
import boto3
import json

def lambda_handler(event, context):
    # S3 bucket neve és régiója a környezeti változókból
    S3_BUCKET = os.environ.get('S3_BUCKET')
    S3_REGION = os.environ.get('AWS_DEFAULT_REGION')

    s3_client = boto3.client('s3', region_name=S3_REGION)

    # A CSV fájl kulcsa az S3-ban
    s3_key = 'registration_data.csv'

    # Aktuális dátum (év-hónap-nap formátumban)
    from datetime import datetime
    today = datetime.utcnow().strftime('%Y-%m-%d')

    # Inicializáljuk a regisztrációk számát 1-re
    registrations = 1

    # Ellenőrizzük, hogy a fájl létezik-e
    try:
        s3_client.head_object(Bucket=S3_BUCKET, Key=s3_key)
        file_exists = True
    except s3_client.exceptions.ClientError as e:
        if e.response['Error']['Code'] == "404":
            file_exists = False
        else:
            raise e

    # Ha a fájl nem létezik, létrehozzuk
    if not file_exists:
        initial_content = 'date,registrations\n'
        s3_client.put_object(
            Bucket=S3_BUCKET,
            Key=s3_key,
            Body=initial_content.encode('utf-8'),
            ContentType='text/csv'
        )

    # Letöltjük a fájlt az S3-ból
    s3_object = s3_client.get_object(Bucket=S3_BUCKET, Key=s3_key)
    existing_content = s3_object['Body'].read().decode('utf-8')
    version_id = s3_object.get('VersionId')

    # Beolvasás CSV-ként
    import csv
    from io import StringIO

    csv_file = StringIO(existing_content)
    reader = csv.reader(csv_file)
    rows = list(reader)

    # Ellenőrizzük, hogy a mai dátum már szerepel-e
    date_found = False
    for row in rows:
        if row[0] == 'date':
            continue  # Fejléc sor
        if row[0] == today:
            # Ha megtaláltuk a mai dátumot, növeljük a számot
            registrations = int(row[1]) + 1
            row[1] = str(registrations)
            date_found = True
            break

    if not date_found:
        # Ha a mai dátum még nincs benne, hozzáadjuk
        rows.append([today, '1'])

    # Újra létrehozzuk a CSV tartalmat
    output = StringIO()
    writer = csv.writer(output)
    writer.writerows(rows)
    updated_content = output.getvalue()

    # Feltöltjük az új tartalmat az S3-ba
    s3_client.put_object(
        Bucket=S3_BUCKET,
        Key=s3_key,
        Body=updated_content.encode('utf-8'),
        ContentType='text/csv'
    )

    # Töröljük a régi verziót, ha van
    if version_id:
        try:
            s3_client.delete_object(Bucket=S3_BUCKET, Key=s3_key, VersionId=version_id)
        except Exception as e:
            print(f"Hiba a régi verzió törlésekor: {e}")

    return {
        'statusCode': 200,
        'body': json.dumps('A regisztrációk száma sikeresen frissítve')
    }
