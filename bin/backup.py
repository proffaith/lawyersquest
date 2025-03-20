import subprocess

BACKUP_FILENAME="MSBABlog_$(date +%Y-%m-%d_%H-%M-%S).sql"
print(f"{str(BACKUP_FILENAME)}")

# Define the command to execute the backup script
backup_command = "/usr/local/mysql/bin/mysqldump -u root -p2wgyoss99*123 MSBABlog > /Users/timfaith/sites/backups/" + BACKUP_FILENAME

print(f"{str(backup_command)}")

# Execute the backup command
try:
    subprocess.call(backup_command, shell=True)
    print(f"Backup Completed Successfully.")

except Exception as e:
    print(f"An error occurred while getting the search results: {str(e)}")
