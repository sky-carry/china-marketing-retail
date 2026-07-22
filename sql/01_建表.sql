-- 库存核对平台 · 建表语句（由 inventory_check 库导出）
-- 先执行: CREATE DATABASE inventory_check ENCODING 'UTF8';
-- 数据装载见 etl/load_excel.py（伯俊 API 版见 etl/sync_bojun.py）

CREATE TABLE "bojun_offline_inventory" (
  "store_warehouse" text,
  "product_code" text,
  "style_no" text,
  "product_name" text,
  "standard_price" double precision,
  "stock_qty" bigint,
  "stock_amount" double precision,
  "boxed_stock" bigint,
  "unit_on_order" bigint,
  "boxed_on_order" bigint,
  "on_order_amount" bigint,
  "in_transit_qty" bigint,
  "in_transit_amount" double precision,
  "frozen_qty" bigint,
  "oms_frozen_qty" bigint,
  "expected_qty" bigint,
  "expected_amount" double precision,
  "reorder_allocatable" bigint,
  "allocatable" bigint,
  "asi" bigint,
  "available" text
);
COMMENT ON TABLE "bojun_offline_inventory" IS '伯俊线下库存（伯俊线下库存.xlsx / download）';
COMMENT ON COLUMN "bojun_offline_inventory"."store_warehouse" IS '店仓';
COMMENT ON COLUMN "bojun_offline_inventory"."product_code" IS '产品编码';
COMMENT ON COLUMN "bojun_offline_inventory"."style_no" IS '款号';
COMMENT ON COLUMN "bojun_offline_inventory"."product_name" IS '品名';
COMMENT ON COLUMN "bojun_offline_inventory"."standard_price" IS '标准价';
COMMENT ON COLUMN "bojun_offline_inventory"."stock_qty" IS '库存数量';
COMMENT ON COLUMN "bojun_offline_inventory"."stock_amount" IS '库存金额';
COMMENT ON COLUMN "bojun_offline_inventory"."boxed_stock" IS '箱内库存';
COMMENT ON COLUMN "bojun_offline_inventory"."unit_on_order" IS '单件在单';
COMMENT ON COLUMN "bojun_offline_inventory"."boxed_on_order" IS '箱内在单';
COMMENT ON COLUMN "bojun_offline_inventory"."on_order_amount" IS '在单金额';
COMMENT ON COLUMN "bojun_offline_inventory"."in_transit_qty" IS '在途数量';
COMMENT ON COLUMN "bojun_offline_inventory"."in_transit_amount" IS '在途金额';
COMMENT ON COLUMN "bojun_offline_inventory"."frozen_qty" IS '冻结量';
COMMENT ON COLUMN "bojun_offline_inventory"."oms_frozen_qty" IS 'OMS冻结量';
COMMENT ON COLUMN "bojun_offline_inventory"."expected_qty" IS '预计数量';
COMMENT ON COLUMN "bojun_offline_inventory"."expected_amount" IS '预计金额';
COMMENT ON COLUMN "bojun_offline_inventory"."reorder_allocatable" IS '追单可配';
COMMENT ON COLUMN "bojun_offline_inventory"."allocatable" IS '可配';
COMMENT ON COLUMN "bojun_offline_inventory"."asi" IS 'ASI';
COMMENT ON COLUMN "bojun_offline_inventory"."available" IS '可用';

CREATE TABLE "feishu_jd_outlet" (
  "store_code" text,
  "store_name" text,
  "video_status" text,
  "store_type" text,
  "remark" text,
  "dealer" text,
  "merchant_store_code" text,
  "hourly_store_code" text,
  "city" text,
  "batch" text,
  "district" text,
  "store_address" text,
  "business_status" text,
  "store_status" text,
  "hourly_business_status" text,
  "extra_status" text,
  "match_table_status" text,
  "verification_status" text
);
COMMENT ON TABLE "feishu_jd_outlet" IS '即时零售门店上翻明细-京东网点（飞书文档附表）';
COMMENT ON COLUMN "feishu_jd_outlet"."store_code" IS '门店编号';
COMMENT ON COLUMN "feishu_jd_outlet"."store_name" IS '门店名称';
COMMENT ON COLUMN "feishu_jd_outlet"."video_status" IS '视频状态';
COMMENT ON COLUMN "feishu_jd_outlet"."store_type" IS '门店性质';
COMMENT ON COLUMN "feishu_jd_outlet"."remark" IS '备注';
COMMENT ON COLUMN "feishu_jd_outlet"."dealer" IS '经销商';
COMMENT ON COLUMN "feishu_jd_outlet"."merchant_store_code" IS '商家门店编号';
COMMENT ON COLUMN "feishu_jd_outlet"."hourly_store_code" IS '小时购门店编号';
COMMENT ON COLUMN "feishu_jd_outlet"."city" IS '所在城市';
COMMENT ON COLUMN "feishu_jd_outlet"."batch" IS '批次';
COMMENT ON COLUMN "feishu_jd_outlet"."district" IS '行政区';
COMMENT ON COLUMN "feishu_jd_outlet"."store_address" IS '门店地址';
COMMENT ON COLUMN "feishu_jd_outlet"."business_status" IS '营业状态';
COMMENT ON COLUMN "feishu_jd_outlet"."store_status" IS '门店状态';
COMMENT ON COLUMN "feishu_jd_outlet"."hourly_business_status" IS '小时购营业状态';
COMMENT ON COLUMN "feishu_jd_outlet"."extra_status" IS '_blank';
COMMENT ON COLUMN "feishu_jd_outlet"."match_table_status" IS '匹配表状态';
COMMENT ON COLUMN "feishu_jd_outlet"."verification_status" IS '验真状态';

CREATE TABLE "feishu_meituan_outlet" (
  "store_name" text,
  "store_id" text,
  "internal_code" text,
  "business_status" text,
  "store_type" text,
  "dealer" text,
  "warning_status" text,
  "city" text,
  "contact_phone" text,
  "store_address" text,
  "business_hours" text,
  "delivery_method" text
);
COMMENT ON TABLE "feishu_meituan_outlet" IS '即时零售门店上翻明细-美团网点（飞书文档附表）';
COMMENT ON COLUMN "feishu_meituan_outlet"."store_name" IS '门店名称';
COMMENT ON COLUMN "feishu_meituan_outlet"."store_id" IS '门店ID';
COMMENT ON COLUMN "feishu_meituan_outlet"."internal_code" IS '内部编码';
COMMENT ON COLUMN "feishu_meituan_outlet"."business_status" IS '营业状态';
COMMENT ON COLUMN "feishu_meituan_outlet"."store_type" IS '门店类型';
COMMENT ON COLUMN "feishu_meituan_outlet"."dealer" IS '经销商';
COMMENT ON COLUMN "feishu_meituan_outlet"."warning_status" IS '预警情况';
COMMENT ON COLUMN "feishu_meituan_outlet"."city" IS '所在城市';
COMMENT ON COLUMN "feishu_meituan_outlet"."contact_phone" IS '联系电话';
COMMENT ON COLUMN "feishu_meituan_outlet"."store_address" IS '门店地址';
COMMENT ON COLUMN "feishu_meituan_outlet"."business_hours" IS '营业时间';
COMMENT ON COLUMN "feishu_meituan_outlet"."delivery_method" IS '配送方式';

CREATE TABLE "feishu_region_contact" (
  "primary_dealer" text,
  "region" text,
  "region_manager" text,
  "instant_retail_contact" text
);
COMMENT ON TABLE "feishu_region_contact" IS '即时零售门店上翻明细-各区域对接人明细（飞书文档附表）';
COMMENT ON COLUMN "feishu_region_contact"."primary_dealer" IS '一级经销商';
COMMENT ON COLUMN "feishu_region_contact"."region" IS '区域';
COMMENT ON COLUMN "feishu_region_contact"."region_manager" IS '区域经理';
COMMENT ON COLUMN "feishu_region_contact"."instant_retail_contact" IS '即时零售对接人';

CREATE TABLE "feishu_store_mapping" (
  "seq_no" text,
  "province" text,
  "city" text,
  "customer_name" text,
  "store_name" text,
  "internal_code" text,
  "remark" text,
  "jd_name" text,
  "jd_id" text,
  "jd_business_status" text,
  "meituan_name" text,
  "meituan_id" text,
  "meituan_business_status" text,
  "eleme_name" text,
  "eleme_id" text,
  "eleme_business_status" text,
  "jd_enable_status" double precision,
  "verification_status" double precision,
  "store_address" text,
  "id" bigint
);
COMMENT ON TABLE "feishu_store_mapping" IS '即时零售门店上翻明细-专卖店（飞书文档主表：三平台门店映射）';
COMMENT ON COLUMN "feishu_store_mapping"."seq_no" IS '序号';
COMMENT ON COLUMN "feishu_store_mapping"."province" IS '省份';
COMMENT ON COLUMN "feishu_store_mapping"."city" IS '城市';
COMMENT ON COLUMN "feishu_store_mapping"."customer_name" IS '客户名称';
COMMENT ON COLUMN "feishu_store_mapping"."store_name" IS '门店名称';
COMMENT ON COLUMN "feishu_store_mapping"."internal_code" IS '内部编码';
COMMENT ON COLUMN "feishu_store_mapping"."remark" IS '备注';
COMMENT ON COLUMN "feishu_store_mapping"."jd_name" IS '京东名称';
COMMENT ON COLUMN "feishu_store_mapping"."jd_id" IS '京东ID';
COMMENT ON COLUMN "feishu_store_mapping"."jd_business_status" IS '京东营业状态';
COMMENT ON COLUMN "feishu_store_mapping"."meituan_name" IS '美团名称';
COMMENT ON COLUMN "feishu_store_mapping"."meituan_id" IS '美团ID';
COMMENT ON COLUMN "feishu_store_mapping"."meituan_business_status" IS '美团营业状态';
COMMENT ON COLUMN "feishu_store_mapping"."eleme_name" IS '饿了么名称';
COMMENT ON COLUMN "feishu_store_mapping"."eleme_id" IS '饿了么ID';
COMMENT ON COLUMN "feishu_store_mapping"."eleme_business_status" IS '饿了么营业状态';
COMMENT ON COLUMN "feishu_store_mapping"."jd_enable_status" IS '京东启用状态';
COMMENT ON COLUMN "feishu_store_mapping"."verification_status" IS '验真状态';
COMMENT ON COLUMN "feishu_store_mapping"."store_address" IS '门店地址（来自 专卖店详细信息.xlsx，按店仓名称匹配）';
COMMENT ON COLUMN "feishu_store_mapping"."id" IS '自增行ID（数据管理在线编辑用，非业务字段）';

CREATE TABLE "jd_store" (
  "store_code" text,
  "store_name" text,
  "merchant_store_code" text,
  "hourly_store_code" text,
  "merchant_name" text,
  "merchant_code" text,
  "city" text,
  "district" text,
  "business_hours" text,
  "store_phone" text,
  "store_mobile" text,
  "store_address" text,
  "created_at" text,
  "updated_at" text,
  "last_operator" text,
  "business_status" text,
  "store_status" text,
  "hourly_business_status" text,
  "store_qualification" text,
  "delivery_capacity_status" text,
  "miaosong_store_link" double precision,
  "daojia_store_link" double precision
);
COMMENT ON TABLE "jd_store" IS '京东门店（京东门店.xls / 门店导出）';
COMMENT ON COLUMN "jd_store"."store_code" IS '门店编号';
COMMENT ON COLUMN "jd_store"."store_name" IS '门店名称';
COMMENT ON COLUMN "jd_store"."merchant_store_code" IS '商家门店编号';
COMMENT ON COLUMN "jd_store"."hourly_store_code" IS '小时购门店编号';
COMMENT ON COLUMN "jd_store"."merchant_name" IS '商家名称';
COMMENT ON COLUMN "jd_store"."merchant_code" IS '商家编号';
COMMENT ON COLUMN "jd_store"."city" IS '所在城市';
COMMENT ON COLUMN "jd_store"."district" IS '行政区';
COMMENT ON COLUMN "jd_store"."business_hours" IS '营业时间';
COMMENT ON COLUMN "jd_store"."store_phone" IS '门店电话';
COMMENT ON COLUMN "jd_store"."store_mobile" IS '门店手机';
COMMENT ON COLUMN "jd_store"."store_address" IS '门店地址';
COMMENT ON COLUMN "jd_store"."created_at" IS '创建时间';
COMMENT ON COLUMN "jd_store"."updated_at" IS '更新时间';
COMMENT ON COLUMN "jd_store"."last_operator" IS '最后一次操作人';
COMMENT ON COLUMN "jd_store"."business_status" IS '营业状态';
COMMENT ON COLUMN "jd_store"."store_status" IS '门店状态';
COMMENT ON COLUMN "jd_store"."hourly_business_status" IS '小时购营业状态';
COMMENT ON COLUMN "jd_store"."store_qualification" IS '门店资质';
COMMENT ON COLUMN "jd_store"."delivery_capacity_status" IS '运力状态（只开通到店团购商家无需关注）';
COMMENT ON COLUMN "jd_store"."miaosong_store_link" IS '秒送门祥链接';
COMMENT ON COLUMN "jd_store"."daojia_store_link" IS '到家门祥链接';

CREATE TABLE "jd_store_inventory" (
  "store_code" text,
  "store_name" text,
  "sku_code" text,
  "product_name" text,
  "merchant_product_code" text,
  "barcode" text,
  "sales_city" text,
  "member_price" double precision,
  "store_price" bigint,
  "onhand_stock" bigint,
  "realtime_price" bigint,
  "available_stock" bigint,
  "product_status" text,
  "stock_status" text,
  "spu_code" text,
  "sales_attr_name" text,
  "guide_price" double precision,
  "jd_sku_code" text
);
COMMENT ON TABLE "jd_store_inventory" IS '京东门店库存（京东门店库存-新.xlsx，商家商品编号补全版）';
COMMENT ON COLUMN "jd_store_inventory"."store_code" IS '门店编号';
COMMENT ON COLUMN "jd_store_inventory"."store_name" IS '门店名称';
COMMENT ON COLUMN "jd_store_inventory"."sku_code" IS 'SKU编码';
COMMENT ON COLUMN "jd_store_inventory"."product_name" IS '商品名称';
COMMENT ON COLUMN "jd_store_inventory"."merchant_product_code" IS '商家商品编号';
COMMENT ON COLUMN "jd_store_inventory"."barcode" IS '条码';
COMMENT ON COLUMN "jd_store_inventory"."sales_city" IS '销售城市';
COMMENT ON COLUMN "jd_store_inventory"."member_price" IS '会员价';
COMMENT ON COLUMN "jd_store_inventory"."store_price" IS '门店价格';
COMMENT ON COLUMN "jd_store_inventory"."onhand_stock" IS '现货库存';
COMMENT ON COLUMN "jd_store_inventory"."realtime_price" IS '实时价';
COMMENT ON COLUMN "jd_store_inventory"."available_stock" IS '可用库存';
COMMENT ON COLUMN "jd_store_inventory"."product_status" IS '商品状态';
COMMENT ON COLUMN "jd_store_inventory"."stock_status" IS '库存状态';
COMMENT ON COLUMN "jd_store_inventory"."spu_code" IS 'SPU编码';
COMMENT ON COLUMN "jd_store_inventory"."sales_attr_name" IS '销售属性名称';
COMMENT ON COLUMN "jd_store_inventory"."guide_price" IS '指导价';
COMMENT ON COLUMN "jd_store_inventory"."jd_sku_code" IS '京东SKU编码';

CREATE TABLE "meituan_store" (
  "store_name" text,
  "store_id" text,
  "internal_code" text,
  "business_status" text,
  "offline_reason" double precision,
  "city" text,
  "contact_phone" text,
  "store_address" text,
  "business_hours" text,
  "delivery_method" text
);
COMMENT ON TABLE "meituan_store" IS '美团门店（美团门店.xlsx / Sheet0）';
COMMENT ON COLUMN "meituan_store"."store_name" IS '门店名称';
COMMENT ON COLUMN "meituan_store"."store_id" IS '门店ID';
COMMENT ON COLUMN "meituan_store"."internal_code" IS '内部编码';
COMMENT ON COLUMN "meituan_store"."business_status" IS '营业状态';
COMMENT ON COLUMN "meituan_store"."offline_reason" IS '休息/下线原因';
COMMENT ON COLUMN "meituan_store"."city" IS '所在城市';
COMMENT ON COLUMN "meituan_store"."contact_phone" IS '联系电话';
COMMENT ON COLUMN "meituan_store"."store_address" IS '门店地址';
COMMENT ON COLUMN "meituan_store"."business_hours" IS '营业时间';
COMMENT ON COLUMN "meituan_store"."delivery_method" IS '配送方式';

CREATE TABLE "meituan_store_inventory" (
  "store_id" text,
  "store_name" text,
  "province_city" text,
  "product_name" text,
  "internal_sku_code" text,
  "sku_id" text,
  "spec_name" text,
  "stock_qty" bigint
);
COMMENT ON TABLE "meituan_store_inventory" IS '美团门店库存（Excel 上传 / 商品明细）';
COMMENT ON COLUMN "meituan_store_inventory"."store_id" IS '门店ID';
COMMENT ON COLUMN "meituan_store_inventory"."store_name" IS '门店名称';
COMMENT ON COLUMN "meituan_store_inventory"."province_city" IS '省份/城市';
COMMENT ON COLUMN "meituan_store_inventory"."product_name" IS '商品名称';
COMMENT ON COLUMN "meituan_store_inventory"."internal_sku_code" IS '店内码/货号';
COMMENT ON COLUMN "meituan_store_inventory"."sku_id" IS 'sku_id';
COMMENT ON COLUMN "meituan_store_inventory"."spec_name" IS '规格名称';
COMMENT ON COLUMN "meituan_store_inventory"."stock_qty" IS '库存';

-- 运行时辅助表（由应用自动创建）
-- store_alias: 门店别名人工对照（sql/02_核对视图.sql 中 IF NOT EXISTS 创建）
-- data_meta:   数据装载时间（loader 维护）
-- upload_log:  看板上传历史（app 自动建表）
