DROP TABLE IF EXISTS lineitem;
DROP TABLE IF EXISTS orders;
DROP TABLE IF EXISTS partsupp;
DROP TABLE IF EXISTS part;
DROP TABLE IF EXISTS customer;
DROP TABLE IF EXISTS supplier;
DROP TABLE IF EXISTS nation;
DROP TABLE IF EXISTS region;

CREATE TABLE region (
    r_regionkey INTEGER PRIMARY KEY,
    r_name VARCHAR(25),
    r_comment VARCHAR(152)
);

CREATE TABLE nation (
    n_nationkey INTEGER PRIMARY KEY,
    n_name VARCHAR(25),
    n_regionkey INTEGER,
    n_comment VARCHAR(152)
);

CREATE TABLE supplier (
    s_suppkey INTEGER PRIMARY KEY,
    s_name VARCHAR(25),
    s_address VARCHAR(40),
    s_nationkey INTEGER,
    s_phone VARCHAR(15),
    s_acctbal NUMERIC(15, 2),
    s_comment VARCHAR(101)
);

CREATE TABLE customer (
    c_custkey INTEGER PRIMARY KEY,
    c_name VARCHAR(25),
    c_address VARCHAR(40),
    c_nationkey INTEGER,
    c_phone VARCHAR(15),
    c_acctbal NUMERIC(15, 2),
    c_mktsegment VARCHAR(10),
    c_comment VARCHAR(117)
);

CREATE TABLE part (
    p_partkey INTEGER PRIMARY KEY,
    p_name VARCHAR(55),
    p_mfgr VARCHAR(25),
    p_brand VARCHAR(10),
    p_type VARCHAR(25),
    p_size INTEGER,
    p_container VARCHAR(10),
    p_retailprice NUMERIC(15, 2),
    p_comment VARCHAR(23)
);

CREATE TABLE partsupp (
    ps_partkey INTEGER,
    ps_suppkey INTEGER,
    ps_availqty INTEGER,
    ps_supplycost NUMERIC(15, 2),
    ps_comment VARCHAR(199),
    PRIMARY KEY (ps_partkey, ps_suppkey)
);

CREATE TABLE orders (
    o_orderkey INTEGER PRIMARY KEY,
    o_custkey INTEGER,
    o_orderstatus CHAR(1),
    o_totalprice NUMERIC(15, 2),
    o_orderdate DATE,
    o_orderpriority VARCHAR(15),
    o_clerk VARCHAR(15),
    o_shippriority INTEGER,
    o_comment VARCHAR(79)
);

CREATE TABLE lineitem (
    l_orderkey INTEGER,
    l_partkey INTEGER,
    l_suppkey INTEGER,
    l_linenumber INTEGER,
    l_quantity NUMERIC(15, 2),
    l_extendedprice NUMERIC(15, 2),
    l_discount NUMERIC(15, 2),
    l_tax NUMERIC(15, 2),
    l_returnflag CHAR(1),
    l_linestatus CHAR(1),
    l_shipdate DATE,
    l_commitdate DATE,
    l_receiptdate DATE,
    l_shipinstruct VARCHAR(25),
    l_shipmode VARCHAR(10),
    l_comment VARCHAR(44),
    PRIMARY KEY (l_orderkey, l_linenumber)
);

CREATE INDEX idx_nation_regionkey ON nation(n_regionkey);
CREATE INDEX idx_supplier_nationkey ON supplier(s_nationkey);
CREATE INDEX idx_customer_nationkey ON customer(c_nationkey);
CREATE INDEX idx_orders_custkey ON orders(o_custkey);
CREATE INDEX idx_lineitem_orderkey ON lineitem(l_orderkey);
CREATE INDEX idx_lineitem_partkey ON lineitem(l_partkey);
CREATE INDEX idx_lineitem_suppkey ON lineitem(l_suppkey);
CREATE INDEX idx_partsupp_partkey ON partsupp(ps_partkey);
CREATE INDEX idx_partsupp_suppkey ON partsupp(ps_suppkey);
