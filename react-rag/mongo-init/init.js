const dbName = process.env.MONGO_INITDB_DATABASE || "clean_namu_crawl";
const user   = process.env.MONGO_USER || "raguser";
const pass   = process.env.MONGO_PASS || "ragpass";

db = db.getSiblingDB(dbName);
db.createUser({ user, pwd: pass, roles: [ { role: "readWrite", db: dbName } ] });
print(`[init] created user ${user} on db ${dbName}`);
