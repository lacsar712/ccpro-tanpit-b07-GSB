# TanPit-01 · 南冈鞣场

鞣坑场地图作业台。登录后是按行列铺开的坑位，点坑登记浸液酸碱度并改状态。顶栏可切到**七日放液台**只读专页对账。

## 技术栈

| 层 | 技术 |
| --- | --- |
| Web API | Django 5 · Django Ninja（不是 DRF 视图集） |
| 结构 | Django app `pits`：models / rules / api 分文件 |
| 数据 | Django ORM · PostgreSQL 15 |
| 前端 | Lit 3 Web Component · Vite |
| 部署 | Docker Compose |

## 路径与端口

- 前端：http://localhost:4770
- API：http://localhost:8770
- PostgreSQL：localhost:6170

## 演示账号

`admin` / `123456`，`worker` / `123456`

## 业务规则

坑不可标「已放液」，除非最近一次浸液酸碱度在 **3.5～5.0**。规则在 `backend/pits/rules.py`。

## 七日放液台

- 独立只读专页（顶栏「七日放液台」或 `#/drains`）：只展示，不能改坑态、不能改酸碱；写方法一律 405。
- 口径：按服务器日历（Asia/Shanghai）取**今天往前含今天共 7 个自然日**，只加算窗口内成功拨到「已放液」的事件（`DrainEvent`）。
- 不看场地图当前有多少口已放液坑；坑被拨回非放液态也不抹掉已落库的成功放液历史。
- 每次进入专页都重新请求 `GET /api/drains/seven-day`，不会冻在旧值；在场地图拨成已放液后回来对账，看板数即这七日成功次数。
- 两名工抢同一口鞣制中坑：状态接口在事务内做条件更新（`UPDATE ... WHERE status=旧态`），先提交者改态并落一笔事件，后者 0 行更新返回 **409**，全库只有一笔、看板只加一。

## 快速启动

```bash
cd TanPit/TanPit-01
docker compose up --build
```
