@echo off
echo ---------------------------------------------------
echo  Sende Backup-Befehl an den Urlaubsplaner...
echo ---------------------------------------------------

REM Hier dein Token eintragen, das du in den Settings gespeichert hast:
set TOKEN=quasimo26

REM Der Befehl, der den Server "anruft"
curl "http://127.0.0.1:5000/api/trigger_backup?token=%TOKEN%"

echo.
echo.
echo ---------------------------------------------------
echo  Wenn oben {"status": "success"...} steht, hat es geklappt!
echo  Das Backup liegt im Ordner 'backups' im Programmverzeichnis.
echo ---------------------------------------------------
exit