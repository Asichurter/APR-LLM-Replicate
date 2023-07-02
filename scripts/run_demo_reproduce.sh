
project="/home/user/projects/checkstyle"
buggy_hash="eeee48f2a6d9884304e871e682d24c309e488731"
fixed_hash="e2c6e148a92e01b3c6037b33440ee7006f742793"

cd $project
git reset --hard HEAD
git clean -df
git checkout $buggy_hash
git checkout $fixed_hash -- src/test/java
mvn clean package -Dmaven.test.skip
mvn clean test