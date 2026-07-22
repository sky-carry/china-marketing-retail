-- 门店地图看板视图（会议 2026-07-21《门店网点及业务看板规划讨论》一期口径）
-- 依赖：store_geo（etl/geocode.py 维护的地理编码缓存，IF NOT EXISTS 不随数据刷新重建）
--       feishu_store_mapping / feishu_jd_outlet / feishu_meituan_outlet / 两平台库存表
-- load_excel.py 每次刷新数据后会重跑本文件（在 02_核对视图.sql 之后）。

CREATE TABLE IF NOT EXISTS store_geo (
  address           text PRIMARY KEY,
  lng               double precision,
  lat               double precision,
  adcode            text,
  formatted_address text,
  level             text,
  status            text NOT NULL,
  updated_at        timestamptz NOT NULL DEFAULT now()
);
COMMENT ON TABLE store_geo IS '地址地理编码缓存（高德）：etl/geocode.py 维护，load_excel.py 不会重建此表';
COMMENT ON COLUMN store_geo.address IS '地址文本（去空格后作为主键）';
COMMENT ON COLUMN store_geo.lng IS '经度（高德 GCJ-02 坐标；NULL=尚未编码成功）';
COMMENT ON COLUMN store_geo.lat IS '纬度（高德 GCJ-02 坐标；NULL=尚未编码成功）';
COMMENT ON COLUMN store_geo.adcode IS '高德行政区划代码';
COMMENT ON COLUMN store_geo.formatted_address IS '高德返回的结构化地址';
COMMENT ON COLUMN store_geo.level IS '高德匹配级别（门牌号/兴趣点等，越细定位越准）';
COMMENT ON COLUMN store_geo.status IS '编码状态：ok=成功 / fail=失败（网络错误或无匹配）';
COMMENT ON COLUMN store_geo.updated_at IS '最后一次编码时间';

-- ============ 地图点位 ============
-- 一行 = 地图上一个点。专卖店一店一行（含京东+美团 SKU 数）；网点按平台各一行。
-- 有效口径与网点保障一致：专卖店取在营（备注非 闭店/机场店），京东网点=启用，美团网点=营业中。
-- lng/lat 为 NULL 表示地址缺失或尚未编码成功（前端计入"未定位"）。
CREATE OR REPLACE VIEW v_map_points AS
WITH jd_sku AS (
  SELECT store_code,
         count(DISTINCT merchant_product_code) FILTER (WHERE available_stock > 0) AS sku_cnt
  FROM jd_store_inventory GROUP BY 1
),
mt_sku AS (
  SELECT store_id,
         count(DISTINCT internal_sku_code) FILTER (WHERE stock_qty > 0) AS sku_cnt
  FROM meituan_store_inventory GROUP BY 1
),
stores AS (
  SELECT store_name,
         max(customer_name)         AS customer_name,
         max(province)              AS province,
         max(city)                  AS city,
         max(btrim(store_address))  AS address,
         max(jd_id)                 AS jd_id,
         max(meituan_id)            AS meituan_id
  FROM feishu_store_mapping
  WHERE store_name IS NOT NULL AND COALESCE(remark, '') NOT IN ('闭店', '机场店')
  GROUP BY 1
)
SELECT '专卖店'::text AS point_type, NULL::text AS platform,
       s.store_name   AS name,
       s.customer_name, s.province, s.city, s.address,
       g.lng, g.lat, g.level AS geo_level,
       js.sku_cnt AS jd_sku_cnt,
       ms.sku_cnt AS mt_sku_cnt
FROM stores s
LEFT JOIN store_geo g ON g.status = 'ok' AND g.address = s.address
LEFT JOIN jd_sku js   ON js.store_code = s.jd_id
LEFT JOIN mt_sku ms   ON ms.store_id = s.meituan_id
UNION ALL
SELECT '网点', '京东',
       ot.store_name, ot.dealer, NULL, ot.city, btrim(ot.store_address),
       g.lng, g.lat, g.level,
       js.sku_cnt, NULL
FROM feishu_jd_outlet ot
LEFT JOIN store_geo g ON g.status = 'ok' AND g.address = btrim(ot.store_address)
LEFT JOIN jd_sku js   ON js.store_code = ot.store_code
WHERE ot.store_status = '启用'
UNION ALL
SELECT '网点', '美团',
       mo.store_name, mo.dealer, NULL, mo.city, btrim(mo.store_address),
       g.lng, g.lat, g.level,
       NULL, ms.sku_cnt
FROM feishu_meituan_outlet mo
LEFT JOIN store_geo g ON g.status = 'ok' AND g.address = btrim(mo.store_address)
LEFT JOIN mt_sku ms   ON ms.store_id = mo.store_id
WHERE mo.business_status = '营业中';

COMMENT ON VIEW v_map_points IS '地图看板点位：专卖店（在营）+京东网点（启用）+美团网点（营业中）×经纬度×在售SKU数；lng/lat NULL=未定位';
