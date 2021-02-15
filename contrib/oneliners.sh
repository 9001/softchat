# find wonky unix/video timestamps
fun() { jq -r '.[]|[.time_in_seconds, .timestamp, .author.id, .author.name, .message_id, .message]|join("\r")' < "$1" | awk -F'\r' '{gsub(/%3D/,"",$5);printf "%9.3f %10.3f %7.3f %7.2f l \033[36m%s %s \033[33m\033[76G%s %s\033[0m\n",$1,$2/1000000,$1-o1,($2-o2)/1000000,substr($3,length($3)-10),$4,substr($5,length($5)-10),$6; o1=$1;o2=$2}' | $(which ggrep || which grep) -C7 -E '^ *[^l ]+ +[^l ]+([^l]*) -?[0-9][0-9]+' --color=always; }