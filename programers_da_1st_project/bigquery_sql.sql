-- return, cancelled 횟수 조회
/*
SELECT  
  FORMAT_TIMESTAMP('%Y-%m', o_i.created_at) AS year_month,
  count(case when o_i.status = 'Returned' then 1 end) as returned,
  count(case when o_i.status = 'Cancelled' then 1 end) as cancelled,
  count(o_i.order_id) as order_id
FROM `bigquery-public-data.thelook_ecommerce.inventory_items` i_i
inner join `bigquery-public-data.thelook_ecommerce.order_items` o_i
on i_i.id = o_i.inventory_item_id
group by 1
order by 1
*/
/*
SELECT  
  FORMAT_TIMESTAMP('%Y-%m', o.created_at) AS year_month,
  count(case when o.status = 'Returned' then 1 end) as returned,
  count(case when o.status = 'Cancelled' then 1 end) as cancelled,
  count(o.user_id) as user_id
FROM `bigquery-public-data.thelook_ecommerce.orders` o
group by 1
order by 1
;
*/

-- return, cancel 비율 조회
/*
SELECT  
  FORMAT_TIMESTAMP('%Y-%m', o.created_at) AS year_month,
  round(count(case when o.status = 'Returned' then 1 end) / count(o.user_id), 2) as returned,
  round(count(case when o.status = 'Cancelled' then 1 end)/ count(o.user_id),2 ) as cancelled,
FROM `bigquery-public-data.thelook_ecommerce.orders` o
group by 1
order by 1
;
*/

-- 환불 및 취소를 하지 않은 경우 조회
/*
select 
  FORMAT_TIMESTAMP('%Y-%m', o_i.created_at) AS year_month,
  count(case 
      when o.status != 'Returned' then 1 
      when o.status != 'Cancelled' then 1
  end) as complete,
  STRING_AGG(p.category, ', ') as category
from `bigquery-public-data.thelook_ecommerce.order_items` o_i
join `bigquery-public-data.thelook_ecommerce.orders` o on o_i.order_id = o.order_id
join `bigquery-public-data.thelook_ecommerce.products` p on o_i.product_id = p.id
group by 1
order by 1
;
*/

-- 선호도 상위 항목 조회
/*
WITH CategoryCounts AS (
  SELECT 
    FORMAT_TIMESTAMP('%Y-%m', o_i.created_at) AS year_month,
    p.category,
    COUNT(*) as count
  FROM `bigquery-public-data.thelook_ecommerce.order_items` o_i
  JOIN `bigquery-public-data.thelook_ecommerce.orders` o ON o_i.order_id = o.order_id
  JOIN `bigquery-public-data.thelook_ecommerce.products` p ON o_i.product_id = p.id
  -- WHERE o.status NOT IN ('Returned', 'Cancelled')
  GROUP BY year_month, category
),
RankedCategories AS (
  SELECT 
    year_month,
    category,
    count,
    ROW_NUMBER() OVER(PARTITION BY year_month ORDER BY count DESC) as rank
  FROM CategoryCounts
)
SELECT 
  year_month,
  STRING_AGG(category ORDER BY count DESC LIMIT 5) AS top_categories
FROM RankedCategories
WHERE rank <= 5
GROUP BY year_month
ORDER BY year_month;

*/

-- Intimates 항목을 구매한 유저와 전체 유저의 비율 조회
/*
SELECT 
  FORMAT_TIMESTAMP('%Y-%m', o_i.created_at) AS year_month, 
  round(count(case when p.category = 'Intimates' then 1 end)/count(o_i.user_id),3 )as monthly_user_per_Intimates ,
  count(o_i.user_id) as user_count
FROM `bigquery-public-data.thelook_ecommerce.order_items` o_i
inner JOIN `bigquery-public-data.thelook_ecommerce.orders` o ON o_i.order_id = o.order_id
inner JOIN `bigquery-public-data.thelook_ecommerce.products` p ON o_i.product_id = p.id
GROUP BY year_month
order by 1 asc
*/

-- 위의 선호도 상위 항목 조회하는 쿼리가 문자열을 이어붙여 출력하는 문제를 해결한 쿼리
/*
WITH CategoryCounts AS (
  SELECT 
    FORMAT_TIMESTAMP('%Y-%m', o_i.created_at) AS year_month,
    p.category,
    COUNT(*) as count
  FROM `bigquery-public-data.thelook_ecommerce.order_items` o_i
  JOIN `bigquery-public-data.thelook_ecommerce.orders` o ON o_i.order_id = o.order_id
  JOIN `bigquery-public-data.thelook_ecommerce.products` p ON o_i.product_id = p.id
  GROUP BY year_month, category
),
RankedCategories AS (
  SELECT 
    year_month,
    category,
    count,
    ROW_NUMBER() OVER(PARTITION BY year_month ORDER BY count DESC) as row_num
  FROM CategoryCounts
)
SELECT 
  year_month,
  category,
  count
FROM RankedCategories
WHERE row_num <= 5
ORDER BY year_month ASC, count DESC;
*/

-- total sales and num of item 
/*
select
  FORMAT_TIMESTAMP('%Y-%m', o_i.created_at) AS year_month,
  sum(o_i.sale_price) as sum_sales,
  sum(o.num_of_item) as sum_count_items
from `bigquery-public-data.thelook_ecommerce.order_items` o_i
inner join `bigquery-public-data.thelook_ecommerce.orders` o on o_i.order_id = o.order_id 
where o_i.status = 'Complete'
group by 1
order by 1
*/

--event table 확인용
/*
select e.event_type
from `bigquery-public-data.thelook_ecommerce.events` e
group by 1
*/

-- 성별에 따른 구매 횟수 비율 조회
/*
select 
  FORMAT_TIMESTAMP('%Y-%m', o.created_at) AS year_month,
  round(count(case when o.gender = 'F' then 1 end) / count(case when o.gender = 'M' then 1 end),4 )as female_per_male
from `bigquery-public-data.thelook_ecommerce.orders` o
group by 1
order by 1
*/


-- 위의 쿼리들을 조합하여 한번에 조회하기 위한 쿼리
/*
with count_r_c as(
SELECT  
  FORMAT_TIMESTAMP('%Y-%m', o.created_at) AS year_month,
  count(case when o.status = 'Returned' then 1 end)  as returned,
  count(case when o.status = 'Cancelled' then 1 end)as cancelled,
  count(case when o.gender = 'F' then 1 end) as order_by_female,
  count(case when o.gender = 'M' then 1 end) as order_by_male
FROM `bigquery-public-data.thelook_ecommerce.orders` o
group by 1
order by 1
),
count_user_gen as(
select
  FORMAT_TIMESTAMP('%Y-%m', u.created_at) AS year_month,
  count(distinct u.id) as count_created_user,
  count(case when u.gender = 'F' then 1 end) as female,
  count(case when u.gender = 'M' then 1 end) as male,
  avg(u.age) as age,
  count(case when u.traffic_source = 'Search' then 1 end) as create_search,
  count(case when u.traffic_source = 'Organic' then 1 end) as create_organic,
  count(case when u.traffic_source = 'Display' then 1 end) as create_display,
  count(case when u.traffic_source = 'Facebook' then 1 end) as create_Facebook,
  count(case when u.traffic_source = 'Email' then 1 end) as create_email
from `bigquery-public-data.thelook_ecommerce.users` u
group by 1
order by 1
),
sum_price_itemsnum as(
select
  FORMAT_TIMESTAMP('%Y-%m', o_i.created_at) AS year_month,
  sum(o_i.sale_price) as sum_sales,
  sum(o.num_of_item) as sum_count_items,
  count(distinct o_i.order_id) as order_ids
from `bigquery-public-data.thelook_ecommerce.order_items` o_i
inner join `bigquery-public-data.thelook_ecommerce.orders` o on o_i.order_id = o.order_id 
where o_i.status = 'Complete'
group by 1
order by 1
)
select 
  s.year_month as year_month,
  cug.count_created_user as monthly_created_user,
  s.sum_sales as sum_sales, s.sum_count_items as sum_num_of_items,
  s.order_ids as order_ids,
  cug.age as avg_age,
  cug.female as female, cug.male as male, 
  rc.order_by_female as order_by_female, 
  rc.order_by_male as order_by_male, 
  rc.returned as returned,
  rc.cancelled as cancelled,
  cug.create_search as search,
  cug.create_organic as organic,
  cug.create_display as display,
  cug.create_email as email,
  cug.create_Facebook as facebook
from sum_price_itemsnum s
inner join count_user_gen cug on s.year_month = cug.year_month
inner join count_r_c rc on s.year_month = rc.year_month 
order by 1

*/

-- 어떤 브랜드의 상품이 어떤 도시에 사는 유저가 언제 구매했는지 조회
/*
with tem as(
select 
o.created_at as orders_created_at, 
o_i.order_id as orders_items_order_id, 
u.id as users_id, 
p.id as products_id
from `bigquery-public-data.thelook_ecommerce.order_items` o_i
inner join `bigquery-public-data.thelook_ecommerce.orders` o on o_i.order_id = o.order_id
inner join `bigquery-public-data.thelook_ecommerce.users` u on o_i.user_id = u.id
inner join `bigquery-public-data.thelook_ecommerce.events` e on u.id = e.user_id
inner join `bigquery-public-data.thelook_ecommerce.products` p on o_i.product_id = p.id
)
select 
t.orders_created_at as tem_orders_created,
p.category as products_category,
p.brand as brand,
u.city as city
from tem t
inner join `bigquery-public-data.thelook_ecommerce.products` p on t.products_id = p.id
inner join `bigquery-public-data.thelook_ecommerce.users` u on t.users_id = u.id
limit 10
*/
