#!/bin/bash
export AWS_ACCESS_KEY_ID=000000000000 AWS_SECRET_ACCESS_KEY=000000000000

awslocal s3 mb s3://aw-hpub-local-s3-media

awslocal events put-rule --name "order placed" --event-pattern "{\"source\":[\"hpub.backend\"],\"detail-type\":[\"OrderPlaced\"]}" 
awslocal events put-rule --name "product archived" --event-pattern "{\"source\":[\"hpub.backend\"],\"detail-type\":[\"ProductArchived\"]}"
awslocal events put-rule --name "product draft" --event-pattern "{\"source\":[\"hpub.backend\"],\"detail-type\":[\"ProductDraft\"]}"
awslocal events put-rule --name "product live" --event-pattern "{\"source\":[\"hpub.backend\"],\"detail-type\":[\"ProductLive\"]}"
awslocal events put-rule --name "product withdrawn" --event-pattern "{\"source\":[\"hpub.backend\"],\"detail-type\":[\"ProductWithdrawn\"]}" 