-- 轻量订单管理系统 数据库结构
-- 用法: mysql -u root -p < schema.sql
CREATE DATABASE IF NOT EXISTS order_system DEFAULT CHARACTER SET utf8mb4;
USE order_system;

DROP TABLE IF EXISTS order_items;
DROP TABLE IF EXISTS orders;
DROP TABLE IF EXISTS inventory;
DROP TABLE IF EXISTS product;
DROP TABLE IF EXISTS `user`;

CREATE TABLE `user` (
  id          INT AUTO_INCREMENT PRIMARY KEY,
  username    VARCHAR(50)  NOT NULL UNIQUE,
  password    VARCHAR(100) NOT NULL,
  created_at  DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE product (
  id          INT AUTO_INCREMENT PRIMARY KEY,
  name        VARCHAR(100)    NOT NULL,
  price       DECIMAL(10, 2)  NOT NULL,
  status      VARCHAR(20)     NOT NULL DEFAULT 'ON_SALE',
  created_at  DATETIME        NOT NULL DEFAULT CURRENT_TIMESTAMP,
  CONSTRAINT ck_product_status CHECK (status IN ('ON_SALE', 'OFF_SHELF')),
  CONSTRAINT ck_product_price CHECK (price >= 0)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE inventory (
  product_id  INT      NOT NULL PRIMARY KEY,
  stock       INT      NOT NULL DEFAULT 0,
  updated_at  DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  CONSTRAINT fk_inventory_product FOREIGN KEY (product_id)
      REFERENCES product (id) ON DELETE CASCADE,
  CONSTRAINT ck_inventory_stock CHECK (stock >= 0)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE orders (
  id            INT AUTO_INCREMENT PRIMARY KEY,
  user_id       INT           NOT NULL,
  total_amount  DECIMAL(12, 2) NOT NULL DEFAULT 0.00,
  status        VARCHAR(20)   NOT NULL DEFAULT 'PENDING',
  created_at    DATETIME      NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at    DATETIME      NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  CONSTRAINT fk_orders_user FOREIGN KEY (user_id) REFERENCES `user` (id),
  CONSTRAINT ck_orders_status CHECK (status IN ('PENDING', 'CANCELLED'))
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE order_items (
  id          INT AUTO_INCREMENT PRIMARY KEY,
  order_id    INT           NOT NULL,
  product_id  INT           NOT NULL,
  quantity    INT           NOT NULL,
  price       DECIMAL(10, 2) NOT NULL,
  subtotal    DECIMAL(12, 2) NOT NULL,
  CONSTRAINT fk_items_order   FOREIGN KEY (order_id)   REFERENCES orders (id)  ON DELETE CASCADE,
  CONSTRAINT fk_items_product FOREIGN KEY (product_id) REFERENCES product (id),
  CONSTRAINT ck_items_quantity CHECK (quantity > 0)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
