#!/bin/bash

pluginsDir=$1

#Rename plugin json file and remove the suffix .json
for file in $pluginsDir/*.json; do
    if [ "$file" = "$pluginsDir/index.json" ]; then
        continue
    fi
    mv "$file" "${file%.json}"
done