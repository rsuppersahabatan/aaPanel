#!/bin/bash
PATH=/bin:/sbin:/usr/bin:/usr/sbin:/usr/local/bin:/usr/local/sbin:~/bin
export PATH

serverUrl=https://node.aapanel.com/install
backup_Url=https://jp1-node.aapanel.com/install
mtype=$1
actionType=$2
name=$3
version=$4

check_dash=$(readlink -f /bin/sh)
if [ "$check_dash" = "/usr/bin/dash" ] || [ "$check_dash" = "/bin/dash" ] || [ "$check_dash" = "dash" ]; then
    if [ -f "/usr/bin/bash" ]; then
        ln -sf /usr/bin/bash /bin/sh
    elif [ -f "/bin/bash" ]; then
        ln -sf /bin/bash /bin/sh
    fi
fi

download_file() {
    local save_file="$1"
    local download_path="$2"
    wget --no-check-certificate -O "$save_file" "$serverUrl/$download_path"
    if [ $? -ne 0 ]; then
        echo "|-WARN: download failed from $serverUrl, backup_url to $backup_Url"
        serverUrl="$backup_Url"
        wget --no-check-certificate -O "$save_file" "$serverUrl/$download_path"
    fi
}

if [ ! -f 'lib.sh' ];then
    download_file lib.sh "$mtype/lib.sh"
fi

# Check if lib.sh is empty or not
if [ ! -s 'lib.sh' ]; then
    download_file lib.sh "$mtype/lib.sh"
fi

download_file "$name.sh" "$mtype/$name.sh"
if [ "$actionType" == 'install' ];then
    bash lib.sh
fi

Node_Url=$(echo "$serverUrl" | awk -F/ '{print $3}')
echo "|-INFO: Node_Url: $Node_Url"
sed -i "s/download.bt.cn/$Node_Url/g" $name.sh

bash $name.sh $actionType $version

echo '|-Successify --- Command executed! ---'
