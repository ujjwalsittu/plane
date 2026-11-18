set -e;cd /var/lib/postgresql/data/backups;F=$(ls -t plane-2*.dump|head -1);echo dump: $F
export PGPASSWORD=$POSTGRES_PASSWORD;U=$POSTGRES_USER;D=plane_restore_drill
p(){ psql -h 127.0.0.1 -U $U -v ON_ERROR_STOP=1 -d "$@";}
p postgres -c "DROP DATABASE IF EXISTS $D" -c "CREATE DATABASE $D"
pg_restore -h 127.0.0.1 -U $U -d $D --no-owner --exit-on-error $F
ok=1;for t in workspaces users projects issues issue_comments pages milestones file_assets django_migrations;do
a=$(p plane -tAc "select count(*) from $t");b=$(p $D -tAc "select count(*) from $t")
echo $t live=$a restored=$b;[ "$a" = "$b" ]||ok=0;done
p postgres -c "DROP DATABASE $D"
if [ $ok = 1 ];then echo RESTORE DRILL OK;else echo RESTORE DRILL: counts differ;fi
