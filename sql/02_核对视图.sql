-- 库存核对视图，与《库存核对需求.md》第 5 节一一对应
-- 依赖关系：store_alias(人工别名表) + feishu_store_mapping → v_dim_store → 三个核对视图

-- ============ 0. 门店维度层 ============

-- 人工别名表：只放"飞书门店名 ↔ 伯俊店仓名"需要人工修正的行。
-- 注意是 IF NOT EXISTS：load_excel.py 刷新数据时不会清掉人工维护的内容。
CREATE TABLE IF NOT EXISTS store_alias (
  feishu_store_name text PRIMARY KEY,
  bojun_warehouse   text NOT NULL
);
COMMENT ON TABLE store_alias IS '门店别名人工对照表：飞书门店名 → 伯俊店仓名（名字对不上的门店在此修正，数据刷新不清空）';

-- 统一门店维度视图：所有核对逻辑从这里取门店，口径只此一处。
-- is_active=false 的门店（备注为 闭店/机场店）不参与核对、不进看板。
CREATE OR REPLACE VIEW v_dim_store AS
SELECT DISTINCT
  f.store_name,
  COALESCE(f.customer_name, '（未填客户）') AS customer_name,
  COALESCE(a.bojun_warehouse, f.store_name) AS bojun_warehouse,
  f.jd_id, f.meituan_id, f.eleme_id,
  f.province, f.city, f.remark,
  COALESCE(f.remark, '') NOT IN ('闭店', '机场店') AS is_active
FROM feishu_store_mapping f
LEFT JOIN store_alias a ON a.feishu_store_name = f.store_name
WHERE f.store_name IS NOT NULL;

COMMENT ON VIEW v_dim_store IS '门店维度：飞书主档 + 人工别名修正；is_active=false（备注闭店/机场店）为逻辑删除，不参与核对';

-- ============ 5.1 核对明细 ============
CREATE OR REPLACE VIEW v_recon_detail AS
WITH stores AS (
  SELECT store_name, bojun_warehouse, jd_id, meituan_id
  FROM v_dim_store WHERE is_active
),
bojun_products AS (
  SELECT DISTINCT product_code FROM bojun_offline_inventory
),
bojun AS (
  SELECT s.store_name, b.product_code,
         max(b.product_name) AS product_name,
         sum(b.stock_qty)    AS bojun_qty
  FROM stores s
  JOIN bojun_offline_inventory b ON b.store_warehouse = s.bojun_warehouse
  GROUP BY 1, 2
),
jd AS (
  SELECT s.store_name, j.merchant_product_code AS product_code,
         max(j.product_name)    AS jd_product_name,
         sum(j.available_stock) AS jd_qty,
         max(j.product_status)  AS jd_product_status
  FROM stores s
  JOIN jd_store_inventory j ON j.store_code = s.jd_id
  JOIN bojun_products bp ON bp.product_code = j.merchant_product_code
  GROUP BY 1, 2
),
mt AS (
  SELECT s.store_name, m.internal_sku_code AS product_code,
         max(m.product_name) AS mt_product_name,
         sum(m.stock_qty)    AS mt_qty
  FROM stores s
  JOIN meituan_store_inventory m ON m.store_id = s.meituan_id
  JOIN bojun_products bp ON bp.product_code = m.internal_sku_code
  GROUP BY 1, 2
),
merged AS (
  SELECT
    COALESCE(b.store_name, j.store_name, m.store_name)       AS store_name,
    COALESCE(b.product_code, j.product_code, m.product_code) AS product_code,
    COALESCE(b.product_name, j.jd_product_name, m.mt_product_name) AS product_name,
    b.bojun_qty, j.jd_qty, m.mt_qty, j.jd_product_status
  FROM bojun b
  FULL JOIN jd j ON j.store_name = b.store_name AND j.product_code = b.product_code
  FULL JOIN mt m ON m.store_name = COALESCE(b.store_name, j.store_name)
                AND m.product_code = COALESCE(b.product_code, j.product_code)
),
store_customer AS (
  SELECT store_name, max(customer_name) AS customer_name
  FROM v_dim_store WHERE is_active GROUP BY 1
)
SELECT
  sc.customer_name,
  m.store_name, m.product_code, m.product_name,
  m.bojun_qty, m.jd_qty, m.mt_qty,
  m.jd_qty - COALESCE(m.bojun_qty, 0) AS jd_diff,
  m.mt_qty - COALESCE(m.bojun_qty, 0) AS mt_diff,
  m.jd_product_status,
  CASE
    WHEN m.bojun_qty IS NULL                         THEN '仅平台有货(伯俊无此品)'
    WHEN m.bojun_qty < 0                             THEN '伯俊负库存'
    WHEN m.jd_qty IS NULL AND m.mt_qty IS NULL       THEN '平台均未上架'
    WHEN COALESCE(m.jd_qty, 0) >= 99
      OR COALESCE(m.mt_qty, 0) >= 99                 THEN '平台虚拟库存'
    WHEN COALESCE(m.jd_qty - m.bojun_qty, 0) = 0
     AND COALESCE(m.mt_qty - m.bojun_qty, 0) = 0     THEN '三方一致'
    ELSE '存在差异'
  END AS flag
FROM merged m
LEFT JOIN store_customer sc ON sc.store_name = m.store_name;

COMMENT ON VIEW v_recon_detail IS '库存核对明细：门店×货号，伯俊 vs 京东/美团，差异=平台-伯俊，NULL=未上架；仅含 v_dim_store.is_active 门店';

-- ============ 5.2 门店汇总 ============
CREATE OR REPLACE VIEW v_recon_store_summary AS
SELECT
  store_name,
  count(*)                                          AS product_cnt,
  count(*) FILTER (WHERE bojun_qty IS NOT NULL)     AS bojun_cnt,
  count(*) FILTER (WHERE jd_qty IS NOT NULL)        AS jd_listed,
  count(*) FILTER (WHERE mt_qty IS NOT NULL)        AS mt_listed,
  count(*) FILTER (WHERE flag = '三方一致')          AS match_cnt,
  count(*) FILTER (WHERE jd_diff <> 0)              AS jd_mismatch,
  count(*) FILTER (WHERE mt_diff <> 0)              AS mt_mismatch,
  count(*) FILTER (WHERE flag = '伯俊负库存')        AS negative_cnt,
  count(*) FILTER (WHERE flag = '仅平台有货(伯俊无此品)') AS platform_only_cnt,
  count(*) FILTER (WHERE flag = '平台虚拟库存')      AS virtual_stock_cnt
FROM v_recon_detail
GROUP BY store_name;

COMMENT ON VIEW v_recon_store_summary IS '库存核对门店级汇总：品数/上架数/一致数/差异数';

-- ============ 5.3a 门店未匹配清单 ============
CREATE OR REPLACE VIEW v_store_unmatched AS
SELECT s.store_name, s.bojun_warehouse, s.province, s.city,
       s.jd_id, s.meituan_id, s.eleme_id
FROM v_dim_store s
WHERE s.is_active
  AND NOT EXISTS (SELECT 1 FROM bojun_offline_inventory b
                  WHERE b.store_warehouse = s.bojun_warehouse);

COMMENT ON VIEW v_store_unmatched IS '在营门店中按名字（含别名修正后）仍对不上伯俊店仓的清单（往 store_alias 插对照行即可修复）';

-- ============ 5.3b 商品未匹配清单 ============
CREATE OR REPLACE VIEW v_product_unmatched AS
WITH stores AS (
  SELECT store_name, jd_id, meituan_id FROM v_dim_store WHERE is_active
),
bojun_products AS (
  SELECT DISTINCT product_code FROM bojun_offline_inventory
)
SELECT '京东' AS platform,
       j.merchant_product_code AS platform_code,
       min(j.product_name)     AS product_name,
       min(j.barcode)          AS barcode,
       count(DISTINCT j.store_code) AS store_cnt,
       sum(j.available_stock)  AS total_qty
FROM jd_store_inventory j
JOIN stores s ON s.jd_id = j.store_code
LEFT JOIN bojun_products bp ON bp.product_code = j.merchant_product_code
WHERE bp.product_code IS NULL AND j.merchant_product_code IS NOT NULL
GROUP BY 2
UNION ALL
SELECT '美团',
       m.internal_sku_code,
       min(m.product_name),
       NULL,
       count(DISTINCT m.store_id),
       sum(m.stock_qty)
FROM meituan_store_inventory m
JOIN stores s ON s.meituan_id = m.store_id
LEFT JOIN bojun_products bp ON bp.product_code = m.internal_sku_code
WHERE bp.product_code IS NULL AND m.internal_sku_code IS NOT NULL
GROUP BY 2;

COMMENT ON VIEW v_product_unmatched IS '平台侧商品编码对不上伯俊货号的清单（含条码，供人工补映射）';

-- ============ 5.2b 客户汇总 ============
-- 可核对行 = 至少一个平台已上翻的行（两平台都没挂的行没有可比对象，不进合格率分母）
CREATE OR REPLACE VIEW v_recon_customer_summary AS
SELECT
  customer_name,
  count(DISTINCT store_name)                        AS store_cnt,
  count(*)                                          AS row_cnt,
  count(*) FILTER (WHERE jd_qty IS NOT NULL
                      OR mt_qty IS NOT NULL)        AS checkable_cnt,
  count(*) FILTER (WHERE flag = '三方一致')          AS match_cnt,
  count(*) FILTER (WHERE flag = '存在差异')          AS diff_cnt,
  count(*) FILTER (WHERE flag = '平台虚拟库存')      AS virtual_cnt,
  count(*) FILTER (WHERE flag = '平台均未上架')      AS unlisted_cnt,
  count(*) FILTER (WHERE jd_qty IS NOT NULL)        AS jd_listed,
  count(*) FILTER (WHERE jd_qty IS NOT NULL
                     AND jd_diff = 0)               AS jd_match,
  count(*) FILTER (WHERE mt_qty IS NOT NULL)        AS mt_listed,
  count(*) FILTER (WHERE mt_qty IS NOT NULL
                     AND mt_diff = 0)               AS mt_match
FROM v_recon_detail
GROUP BY customer_name;

COMMENT ON VIEW v_recon_customer_summary IS '客户（公司）级汇总：门店数/行数/一致数/分平台一致数；合格率 = match_cnt / checkable_cnt';
