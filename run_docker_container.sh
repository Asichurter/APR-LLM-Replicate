#!/bin/bash

containername="asichurter-libro"

docker ps -aq --filter "name=$containername" | grep -q . && docker stop $containername && docker rm $containername
docker run -dt --name $containername --env-file ./env.list -v $(pwd)/data:/home/user/data -v $(pwd)/scripts:/home/user/scripts -v $(pwd)/results:/home/user/results greenmon/libro-env:latest
docker exec -it $containername /bin/bash
