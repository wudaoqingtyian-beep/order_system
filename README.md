# 订单管理系统测试实践

自己写的一个小订单系统，用来当接口自动化测试的被测对象。系统是 FastAPI + MySQL，
5 张表、10 个接口，配套做了测试数据的自动生成和按批次清理，接口用例 16 条，全部写在 YAML 里。

接口测试跑在一个接口自动化框架上，这个框架是我自己另外写的一个项目，
YAML 用例加载、HTTP 请求、断言、Allure 报告都由它提供；测试数据由一个独立的数据工厂生成。
这个仓库里放的是被测系统本身、框架和数据工厂的接入层，以及用例。

## 背景

以前练接口自动化都拿 httpbin 这种公开接口，能学会发请求、写断言，但有两件事测不出来：
一是接口返回成功不代表数据库里的数据对了；二是测试数据要么手工准备要么写死 id，
跑第二轮就不成立了。

订单业务刚好能把这两件事覆盖到。创建订单要校验用户和商品、扣库存、写订单和明细，
跨三张表走一个事务，中途失败整体回滚。拿它当被测系统，主要验证两点：
数据能不能自动生成、用完清干净、连跑几轮结果都一样；接口返回和库里实际的数据是不是一致。

## 组成

| 部分 | 说明 |
|---|---|
| 被测系统 | FastAPI + MySQL，5 张表，10 个接口 |
| 测试数据 | 数据工厂生成用户、商品、库存，按 batch_id 批次清理 |
| 接口用例 | 16 条 YAML，接口断言 + 数据库断言 |
| 执行框架 | 接口自动化框架（自己写的），负责加载用例、发请求、断言、生成 Allure 报告 |

一次执行的完整流程：

```
数据工厂造数（用户 / 商品+库存 / 前置订单）
        ↓
订单系统（被测对象，127.0.0.1:8000）
        ↓
框架读 YAML 用例，发真实 HTTP 请求
        ↓
接口断言（状态码、错误码、返回字段）
数据库断言（SQL 查 orders / order_items / inventory）
        ↓
按 batch_id 删除本批数据，断言残留为 0
```

单条用例走一遍的顺序是：setup 声明要什么数据，工厂生成并落库、记下 batch_id；
框架发请求；接口和数据库两层断言；finally 里按 batch_id 清理；fixture 再确认本批残留为 0。
造数中途失败、batch_id 还没返回的情况由 fixture 里的 `cleanup_all()` 兜底，
失败的用例也不会留数据。

## 目录结构

```
order_system/
├── main.py / service.py / db.py    路由、业务逻辑、数据库连接和事务
├── errors.py / schemas.py          错误码、请求响应模型
├── init_db.py / schema.sql         建库建表，带 3 条基础商品
├── e2e_check.py                    手工端到端验证脚本
├── pytest.ini                      默认只跑测试，套件用 -m suite
├── requirements.txt / .env.example
├── testcases/order/                16 条 YAML 用例
└── tests/
    ├── conftest.py                 独立测试库 + 造数清理 fixture
    ├── test_order.py               业务规则和数据库一致性
    ├── test_data_factory.py        数据工厂接入、批次清理
    ├── test_aerotest_order.py      YAML 套件入口
    ├── .batches/                   批次档案，运行时生成，不入库
    ├── data_factory/               数据工厂接入层
    └── aerotest/                   框架接入层（目录名沿用框架自己的名字）
```

## 跑起来

### 目录布局

这个仓库不是独立的，造数和用例执行依赖同级的两个仓库，代码直接引用它们的核心代码目录，
没有复制：

```
工作区/
├── order_system/    本仓库
├── 项目1/           测试数据工厂
└── 项目2/           接口自动化框架
```

项目1、项目2 只是本机给这两个仓库起的目录名，不是什么编号体系。
数据工厂的实际路径可以用环境变量 `DATA_FACTORY_HOME` 指到别处；
框架的路径是写死的，固定找同级的 `项目2`。
两个目录缺任何一个，pytest 收集用例时都会直接报
`RuntimeError: 未找到 AeroTest 框架 core`（报错里的 AeroTest 是框架自己的名字）。

下面的命令都在工作区根目录执行，也就是 order_system 的上一级，
代码里的 import 是按这个布局写的。

### 启动服务

```bash
pip install -r order_system/requirements.txt

# 数据库配置，复制一份改就行，默认 root/123456@127.0.0.1:3306
copy order_system\.env.example order_system\.env     # Windows
# cp order_system/.env.example order_system/.env     # Linux / Mac

python -m order_system.init_db                       # 建库建表，带 3 条基础商品
python -m uvicorn order_system.main:app --host 127.0.0.1 --port 8000
```

启动后 http://127.0.0.1:8000/docs 有 Swagger 页面，可以手动点着试。

### 跑测试

```bash
python -m pytest order_system/tests -q           # 默认测试，27 passed
python -m pytest order_system/tests -m suite -v  # YAML 套件，16 passed，约 20 秒
```

默认测试用 TestClient 进程内调用，连独立测试库 `order_system_test`，不需要先起服务。
YAML 套件走真实 HTTP，要先把服务跑起来。

这两条命令分两次执行，不要用 `-o addopts=""` 合到一个 pytest 进程里，
混跑会把测试数据写进业务库，原因见后面调试记录第 2 条。
`pytest.ini` 里默认 `addopts = -m "not suite"`，所以直接跑 pytest 不会带上套件。

## 接口和表

用例和断言都是照着下面这些约定写的，放在这里方便对照。

### 表

| 表 | 说明 |
|---|---|
| user | 用户：id / username(唯一) / password / created_at |
| product | 商品：id / name / price / status(ON_SALE、OFF_SHELF) / created_at |
| inventory | 库存：product_id(主键外键) / stock / updated_at |
| orders | 订单：id / user_id / total_amount / status(PENDING、CANCELLED) / created_at |
| order_items | 订单明细：order_id / product_id / quantity / price / subtotal |

### 接口

业务接口 7 个：

```
POST /api/users                          创建用户
GET  /api/products                       商品列表
GET  /api/products/{id}                  商品详情
GET  /api/inventory/{product_id}         查询库存
POST /api/orders                         创建订单
GET  /api/orders/{id}                    查询订单及明细
POST /api/orders/{id}/cancel             取消订单并恢复库存
```

测试辅助接口 3 个，造数据用，不属于业务主流程：

```
POST /api/products/setup                 创建商品并设置库存
POST /api/products/{id}/inventory        重置库存
PUT  /api/products/{id}/status           上架 / 下架
```

响应格式统一：

```json
{ "code": 0, "message": "ok", "data": { } }
```

`code` 为 0 表示成功，非 0 是业务错误码，写死在代码里，适合做自动化断言：

| code | 含义 |
|---|---|
| 1001 | 用户不存在 |
| 1002 | 用户名已存在 |
| 2001 | 商品不存在 |
| 2002 | 商品已下架，不可购买 |
| 3002 | 库存不足 |
| 3003 | 购买数量必须大于 0 |
| 4001 | 订单不存在 |
| 4002 | 订单已取消，不能重复取消 |
| 4003 | 当前订单状态不允许取消 |
| 9001 | 请求参数不合法 |

失败响应的 `data` 固定为 `null`。

### 下单事务

创建订单在一个事务里执行，任何一步失败整体回滚：

```
校验用户存在
→ 合并同商品数量、校验数量 > 0
→ 校验商品存在（SELECT ... FOR UPDATE 加行锁）
→ 校验商品是 ON_SALE
→ 校验库存充足
→ 扣减库存
→ 写订单（PENDING）
→ 写订单明细
```

`FOR UPDATE` 给商品和库存行加锁，让校验和扣减在同一事务里看到同一份数据。
这里只有实现，没有做过并发压测，超卖与否没有实测结论。

取消订单只允许 PENDING 状态，先恢复库存再改状态。重复取消返回 4002，库存不再变动。

金额全程用 Decimal 计算，数据库列也是 DECIMAL。

## 用例

16 条都在 `testcases/order/` 下。其中 14 条带 `db_eq` 数据库断言，
另外 2 条（查询订单不存在、取消订单不存在）不涉及数据落库，只做接口断言。

### 创建订单（10 条）

| 用例 | 场景 | 关键断言 |
|---|---|---|
| `order_create_success` | 正常下单（50.00 × 3） | 200 / code=0 / PENDING / 总额 150.0 / 库存 10 → 7 |
| `order_create_multi_items` | 多商品下单（10.00×2 + 20.50×1） | 总额 40.5 / 库里 "40.50" / 明细 2 条 / 库存各减各的 |
| `order_create_stock_exact` | 边界，库存刚好（10 买 10） | 成功 / 总额 100.0 / 库存精确归零 / 明细单价快照 "10.00" |
| `order_create_stock_not_enough` | 库存不足（3 买 5） | 400 / 3002 / 无订单落库 / 库存保持 3 |
| `order_create_product_not_found` | 商品不存在 | 400 / 2001 / 无订单落库 |
| `order_create_product_off_shelf` | 商品已下架 | 400 / 2002 / 无订单落库 / 库存保持 10 |
| `order_create_quantity_zero` | 边界，数量 0 | 400 / 3003 / 无订单落库 |
| `order_create_quantity_negative` | 边界，数量 -1 | 400 / 3003 / 库存保持 10，不会反向加库存 |
| `order_create_user_not_found` | 用户不存在 | 400 / 1001 / 无订单落库 |
| `order_create_items_empty` | items 传空数组 | 422 / 9001 / 无订单落库 |

### 状态流转（3 条）

| 用例 | 场景 | 关键断言 |
|---|---|---|
| `order_cancel_success` | 正常取消（下单 4 件后取消） | 200 / CANCELLED，接口和库里一致 / 库存 6 → 10 恢复 |
| `order_cancel_duplicate` | 重复取消 | 400 / 4002 / 状态仍 CANCELLED / 库存停在 10，不二次增加 |
| `order_cancel_not_found` | 取消不存在的订单，不用造数 | 400 / 4001 / data=null |

### 查询与数据一致性（3 条）

| 用例 | 场景 | 关键断言 |
|---|---|---|
| `order_db_inventory_after_create` | 下单后接口读数和库里读数是否一致 | 接口 stock=7，SQL 查出来也是 7 |
| `order_db_inventory_after_cancel` | 取消后两边库存是否一致 | 接口和 SQL 都是 10 / 订单落库为 CANCELLED |
| `order_get_not_found` | 查询不存在的订单，不用造数 | 400 / 4001 / message=订单不存在 |

### 例子

拿库存不足这条看，数据全部来自 setup 造数，用例里不写死数据库 id：

```yaml
name: 创建订单-库存不足
# 目的：stock=3 / quantity=5，接口返回库存不足；事务回滚：无订单、库存不变
setup:
  - template: user
    var: user_id
  - template: product
    var: product_id
    price: 30.00
    stock: 3
    status: ON_SALE
request:
  method: POST
  path: /api/orders
  json:
    user_id: "${user_id}"
    items:
      - product_id: "${product_id}"
        quantity: 5
assertions:
  - type: status_eq
    expected: 400
  - type: json_eq                # 3002 库存不足
    path: $.code
    expected: 3002
  - type: json_eq
    path: $.message
    expected: 库存不足
  - type: json_eq                # 失败响应不带业务数据
    path: $.data
    expected: null
  - type: db_eq                  # 数据库：没有任何订单落库
    sql: "SELECT COUNT(*) c FROM orders WHERE user_id = ${user_id}"
    field: c
    expected: 0
  - type: db_eq                  # 数据库：库存保持 3
    sql: "SELECT stock FROM inventory WHERE product_id = ${product_id}"
    field: stock
    expected: 3
```

新增一条正常场景的用例就是加一个 YAML 文件，不用写 Python。
加载的时候会校验 method、断言类型和 `${var}` 来源，写错了收集阶段就报错。

## 测试数据

造数复用测试数据工厂的生成能力（本机目录 `项目1`；Faker 规则、YAML 模板），
本仓库只写接入层，工厂代码没有改动：

```
factory_bridge.py       调工厂的 core 生成数据，模板在 tests/data_factory/templates/
order_data_factory.py   数据经业务 API 落库，登记 batch_id
cleanup()               按主键删除：明细 → 订单 → 库存 → 商品 → 用户
```

batch_id 形如 `test_order_20261003_120000_ab12`，每批在 `tests/.batches/` 下有一份档案，
记着这批造了哪些 user/product/order 和清理结果。清理只删本批的主键，
批次之间互不影响，重复执行也没问题。

测试里大概是这样：

```python
def test_stock_not_enough(data_factory):
    user = data_factory.create_user()                                # 自动生成用户
    product = data_factory.create_product(stock=3, status="ON_SALE")  # 自动生成商品和库存
    body = data_factory.place_order(user["id"], [{"product_id": product["id"], "quantity": 5}])
    assert body["code"] == 3002                                       # 库存不足被拒绝
    # 测完 fixture 自动清理，并断言库里没残留
```

造数走业务接口，不直接写 SQL。直接插库会绕过接口校验和事务，数据不一定合法，
出了问题也分不清是业务的问题还是数据的问题。走接口造出来的数据是合法的，
造的过程顺带把接口也测了。只有清理用 SQL 按主键删，这个场景要的是准确和快。

断言接口的同时也断言数据库。接口返回 200 但事务实际回滚了、库存扣了订单没写、
重复取消把库存加了两次，这些问题接口层看不出来，只能查库。
`order_cancel_duplicate` 里断言库存停在 10 不再增加，
`order_create_stock_not_enough` 里断言没有订单落库、库存保持 3，都是查库才能发现的。

每条用例用自己的数据，不用固定数据。固定的 id 换个环境就不存在了，
上一条用例把库存扣光，下一条必然失败，跑第二轮结果也对不上。
所以 user_id、product_id 都是造数现生成的，断言只针对自己那批数据，
跟库里原来有什么无关。

## 框架接入

YAML 用例的加载、请求、断言、Allure 报告都由同级的接口自动化框架提供（本机目录 `项目2`），
本仓库只写接入部分：

```
testcases/order/*.yaml                  16 条用例
tests/test_aerotest_order.py            pytest 入口，收集 YAML 后交给框架执行
tests/aerotest/provider.py              造数钩子，框架的 setup/teardown 转到数据工厂
tests/aerotest/config/envs/…yaml        环境配置，服务地址和业务库连接
tests/aerotest/framework.py             框架和工厂同名 core 包的共存处理
```

框架本身改了两处：断言支持 `${var}` 变量渲染（否则 SQL 里只能写死 id），
db 断言支持用环境变量指定测试库连接。其余都是复用，内核没动，
框架自己的 42 个单测通过。

订单用例放在被测系统这边而不是框架仓库，因为框架仓库自带一套 httpbin 的示例用例，
两套用例共用 base_url 会互相干扰。

## 调试记录

开发中遇到两个问题，记一下。

1. 失败响应的 data 是 null。调试时全量跑出现 2 failed，失败点是按成功结构取
   `data.id` 抛 TypeError。下单接口返回的是失败响应，data 固定为 null，
   取值前没有判 code；异常发生在登记订单号和清理之前，那批数据也没清掉。
   处理：取值前统一先判业务码；清理挪到 fixture teardown 里无条件执行；
   加了本批残留必须为 0 的断言。

2. 混跑污染业务库。有次用 `-o addopts=""` 把默认测试和套件共 43 项放进同一个
   pytest 进程，跑完业务库计数不对，出现了残留。原因是套件里 session 级的 fixture
   把进程内的 db 指向业务库之后不还原，而部分造数按设计是不清理的，就写进了业务库。
   现在两条命令分开跑，实测各落各的库、计数回基线。框架层面的还原还没做。

## 已知问题

- 没有鉴权，用户身份从请求体里的 user_id 传进来。
- 没做过并发测试。下单用了 `SELECT ... FOR UPDATE` 行锁，但只有实现，
  没有压测数据，超卖与否没有结论。
- YAML 套件要手工起服务，走真实 HTTP；也没接 CI。
- 默认测试和套件不能混在一个 pytest 进程里跑，原因见调试记录第 2 条。
- 服务和数据工厂默认端口都是 8000，不能同时起。
- `tests/test_order.py` 还是用 fixture 简易造数，没迁到数据工厂，
  数据在一次性测试库 `order_system_test` 里，每个 session 重建。
- 断言里的 `${var}` 要运行期才报错，加载期的静态校验只覆盖 request 部分。
- batch_id 的时间戳精确到秒，同一秒的多个批次靠 4 位随机串区分，理论上可能重复。

## 之后想做的

鉴权、并发场景验证库存、套件接 CI、失败重试和残留巡检、混跑时测试库指针的自动还原。
目前都还没做。





