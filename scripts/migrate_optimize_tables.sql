-- =============================================================================
-- Миграция: оптимизация ClickHouse-таблиц
-- Проблемы: ORDER BY tuple() (нет индекса), нет PARTITION BY, нет LowCardinality
-- Подход: создать _new → INSERT SELECT → RENAME → (после проверки) DROP _old
--
-- ВАЖНО: INSERT в большие таблицы (pl1, pl5, pl6 ~9–45 млн строк) занимает
--        несколько минут. Выполнять в часы минимальной нагрузки.
--        После RENAME таблица сразу доступна для запросов.
--        _old таблицы удалять только после проверки в DataLens.
-- =============================================================================


-- ─────────────────────────────────────────────────────────────────────────────
-- fobo.pl1  (P&L по блюдам, ~9.4 млн строк, 1.15 ГБ)
-- ─────────────────────────────────────────────────────────────────────────────

CREATE TABLE fobo.pl1_new
(
    `UniqOrderId_Id`                              String,
    `Department`                                  LowCardinality(String),
    `Department_Id`                               LowCardinality(String),
    `OriginName`                                  Nullable(String),
    `PayTypes`                                    Nullable(String),
    `NonCashPaymentType`                          Nullable(String),
    `OpenDate_Typed`                              Date,
    `HourClose`                                   Nullable(Float32),
    `OrderDiscount_Type`                          LowCardinality(String),
    `DishCategory_Accounting`                     Nullable(String),
    `DishCategory_Accounting_Id`                  Nullable(String),
    `DishCategory`                                LowCardinality(String),
    `DishCategory_Id`                             LowCardinality(String),
    `DishName`                                    Nullable(String),
    `DishId`                                      Nullable(String),
    `DishType`                                    LowCardinality(String),
    `DeletedWithWriteoff`                         LowCardinality(String),
    `OrderDeleted`                                LowCardinality(String),
    `Mounth`                                      LowCardinality(String),
    `YearOpen`                                    LowCardinality(String),
    `DayOfWeekOpen`                               LowCardinality(String),
    `OrderWaiter_Name`                            Nullable(String),
    `ItemSaleEventDiscountType`                   LowCardinality(String),
    `OpenTime`                                    Nullable(String),
    `CloseTime`                                   Nullable(String),
    `TableNum`                                    Nullable(Float32),
    `JurName`                                     LowCardinality(String),
    `Conception`                                  LowCardinality(String),
    `Store_Name`                                  LowCardinality(String),
    `GuestNum`                                    Nullable(Float32),
    `DiscountSum`                                 Nullable(Float32),
    `DishAmountInt`                               Nullable(Float32),
    `DishSumInt`                                  Nullable(Float32),
    `DishDiscountSumInt`                          Nullable(Float32),
    `ProductCostBase_Profit`                      Nullable(Float32),
    `ProductCostBase_ProductCost`                 Nullable(Float32),
    `DishDiscountSumInt_averagePriceWithVAT`       Nullable(Float32),
    `ProductCostBase_Percent`                     Nullable(Float32),
    `GuestNum_Avg`                                Nullable(Float32),
    `DishGroup`                                   LowCardinality(String),
    `Currencies_Currency`                         LowCardinality(String),
    `DishGroup_TopParent`                         LowCardinality(String),
    `DishGroup_SecondParent`                      LowCardinality(String),
    `DishGroup_ThirdParent`                       LowCardinality(String),
    `Department_Category1`                        LowCardinality(String),
    `Department_Category2`                        LowCardinality(String),
    `Department_Category3`                        LowCardinality(String),
    `Department_Category4`                        LowCardinality(String),
    `Department_Category5`                        LowCardinality(String),
    `CookingPlaceType`                            LowCardinality(String),
    `url`                                         LowCardinality(String),
    `DiscountSum_RUB`                             Nullable(Float32),
    `DishAmountInt_RUB`                           Nullable(Float32),
    `DishSumInt_RUB`                              Nullable(Float32),
    `DishDiscountSumInt_RUB`                      Nullable(Float32),
    `ProductCostBase_Profit_RUB`                  Nullable(Float32),
    `ProductCostBase_ProductCost_RUB`             Nullable(Float32),
    `DishDiscountSumInt_averagePriceWithVAT_RUB`  Nullable(Float32),
    `ProductCostBase_Percent_RUB`                 Nullable(Float32),
    `GuestNum_Avg_RUB`                            Nullable(Float32),
    `GuestNum_RUB`                                Nullable(Float32),
    `ProductCostBase_OneItem_RUB`                 Nullable(Float32),
    `DishReturnSum_RUB`                           Nullable(Float32)
)
ENGINE = MergeTree
PARTITION BY toYYYYMM(OpenDate_Typed)
ORDER BY (OpenDate_Typed, Department, DishGroup, DishId)
SETTINGS index_granularity = 8192;

-- Заливка данных (несколько минут для 9.4 млн строк)
INSERT INTO fobo.pl1_new
SELECT
    UniqOrderId_Id,
    Department,
    Department_Id,
    OriginName,
    PayTypes,
    NonCashPaymentType,
    OpenDate_Typed,
    HourClose,
    OrderDiscount_Type,
    DishCategory_Accounting,
    DishCategory_Accounting_Id,
    DishCategory,
    DishCategory_Id,
    DishName,
    DishId,
    DishType,
    DeletedWithWriteoff,
    OrderDeleted,
    Mounth,
    YearOpen,
    DayOfWeekOpen,
    OrderWaiter_Name,
    ItemSaleEventDiscountType,
    OpenTime,
    CloseTime,
    TableNum,
    JurName,
    Conception,
    Store_Name,
    GuestNum,
    DiscountSum,
    DishAmountInt,
    DishSumInt,
    DishDiscountSumInt,
    ProductCostBase_Profit,
    ProductCostBase_ProductCost,
    DishDiscountSumInt_averagePriceWithVAT,
    ProductCostBase_Percent,
    GuestNum_Avg,
    DishGroup,
    Currencies_Currency,
    DishGroup_TopParent,
    DishGroup_SecondParent,
    DishGroup_ThirdParent,
    Department_Category1,
    Department_Category2,
    Department_Category3,
    Department_Category4,
    Department_Category5,
    CookingPlaceType,
    url,
    DiscountSum_RUB,
    DishAmountInt_RUB,
    DishSumInt_RUB,
    DishDiscountSumInt_RUB,
    ProductCostBase_Profit_RUB,
    ProductCostBase_ProductCost_RUB,
    DishDiscountSumInt_averagePriceWithVAT_RUB,
    ProductCostBase_Percent_RUB,
    GuestNum_Avg_RUB,
    GuestNum_RUB,
    ProductCostBase_OneItem_RUB,
    DishReturnSum_RUB
FROM fobo.pl1;

RENAME TABLE fobo.pl1 TO fobo.pl1_old, fobo.pl1_new TO fobo.pl1;
-- После проверки в DataLens: DROP TABLE fobo.pl1_old;


-- ─────────────────────────────────────────────────────────────────────────────
-- fobo.pl2  (транзакции заказов, ~488 тыс строк)
-- ─────────────────────────────────────────────────────────────────────────────

CREATE TABLE fobo.pl2_new
AS fobo.pl2   -- копируем схему как есть
ENGINE = MergeTree
PARTITION BY toYYYYMM(OpenDate_Typed)
ORDER BY (OpenDate_Typed, Department, url);

INSERT INTO fobo.pl2_new SELECT * FROM fobo.pl2;
RENAME TABLE fobo.pl2 TO fobo.pl2_old, fobo.pl2_new TO fobo.pl2;
-- После проверки: DROP TABLE fobo.pl2_old;


-- ─────────────────────────────────────────────────────────────────────────────
-- fobo.pl5  (складские движения, ~45 млн строк — самая тяжёлая)
-- ─────────────────────────────────────────────────────────────────────────────

CREATE TABLE fobo.pl5_new
(
    `Department_JurPerson`          LowCardinality(String),
    `Counteragent_Id`               Nullable(String),
    `Product_Id`                    Nullable(String),
    `Department`                    LowCardinality(String),
    `Department_Code`               LowCardinality(String),
    `Product_Type`                  LowCardinality(String),
    `TransactionType`               LowCardinality(String),
    `Contr_Account_Group`           LowCardinality(String),
    `Contr_Product_TopParent`       LowCardinality(String),
    `Contr_Product_SecondParent`    LowCardinality(String),
    `Contr_Product_ThirdParent`     LowCardinality(String),
    `Product_Name`                  Nullable(String),
    `Contr_Product_Name`            Nullable(String),
    `Product_MeasureUnit`           LowCardinality(String),
    `Product_TopParent`             LowCardinality(String),
    `Product_SecondParent`          LowCardinality(String),
    `Product_ThirdParent`           LowCardinality(String),
    `Account_CounteragentType`      LowCardinality(String),
    `Counteragent_Name`             Nullable(String),
    `DateTime_DateTyped`            Date,
    `DateSecondary_DateTyped`       Nullable(String),
    `Document`                      Nullable(String),
    `Product_Category`              LowCardinality(String),
    `Sum_ResignedSum`               Nullable(Float32),
    `Amount_In`                     Nullable(Float32),
    `Sum_Incoming`                  Nullable(Float32),
    `Amount_Out`                    Nullable(Float32),
    `Sum_Outgoing`                  Nullable(Float32),
    `url`                           LowCardinality(String),
    `Sum_ResignedSum_RUB`           Nullable(Float32),
    `Amount_In_RUB`                 Nullable(Float32),
    `Sum_Incoming_RUB`              Nullable(Float32),
    `Amount_Out_RUB`                Nullable(Float32),
    `Sum_Outgoing_RUB`              Nullable(Float32)
)
ENGINE = MergeTree
PARTITION BY toYYYYMM(DateTime_DateTyped)
ORDER BY (DateTime_DateTyped, Department, TransactionType)
SETTINGS index_granularity = 8192;

INSERT INTO fobo.pl5_new SELECT * FROM fobo.pl5;
RENAME TABLE fobo.pl5 TO fobo.pl5_old, fobo.pl5_new TO fobo.pl5;
-- После проверки: DROP TABLE fobo.pl5_old;


-- ─────────────────────────────────────────────────────────────────────────────
-- fobo.pl6  (тайминги кухни, ~9.3 млн строк)
-- ─────────────────────────────────────────────────────────────────────────────

CREATE TABLE fobo.pl6_new
(
    `DishId`                              Nullable(String),
    `UniqOrderId_Id`                      String,
    `DishCategory_Id`                     LowCardinality(String),
    `CookingPlace_Id`                     Nullable(String),
    `ItemSaleEvent_Id`                    Nullable(String),
    `SoldWithItem_Id`                     Nullable(String),
    `DishName`                            Nullable(String),
    `DeletedWithWriteoff`                 LowCardinality(String),
    `DishGroup`                           LowCardinality(String),
    `DishGroup_TopParent`                 LowCardinality(String),
    `DishGroup_SecondParent`              LowCardinality(String),
    `DishGroup_ThirdParent`               LowCardinality(String),
    `OrderDeleted`                        LowCardinality(String),
    `DishCategory`                        LowCardinality(String),
    `DishCode`                            Nullable(String),
    `CookingPlace`                        Nullable(String),
    `OrderNum`                            Nullable(Float32),
    `CookingPlaceType`                    LowCardinality(String),
    `DishType`                            LowCardinality(String),
    `Department`                          LowCardinality(String),
    `OpenDate_Typed`                      Date,
    `HourClose`                           Nullable(Float32),
    `Cooking_StartDelayTime_Avg`          Nullable(Float32),
    `DishAmountInt`                       Nullable(Float32),
    `Cooking_FeedLateTime_Avg`            Nullable(Float32),
    `Cooking_CookingLateTime_Avg`         Nullable(Float32),
    `Cooking_GuestWaitTime_Avg`           Nullable(Float32),
    `Cooking_ServeTime_Avg`               Nullable(Float32),
    `Cooking_CookingDuration_Avg`         Nullable(Float32),
    `Cooking_Cooking1Duration_Avg`        Nullable(Float32),
    `Cooking_Cooking2Duration_Avg`        Nullable(Float32),
    `Cooking_Cooking3Duration_Avg`        Nullable(Float32),
    `Cooking_Cooking4Duration_Avg`        Nullable(Float32),
    `Cooking_KitchenTime_Avg`             Nullable(Float32),
    `DishDiscountSumInt`                  Nullable(Float32),
    `url`                                 LowCardinality(String),
    `Cooking_StartDelayTime_Avg_RUB`      Nullable(Float32),
    `DishAmountInt_RUB`                   Nullable(Float32),
    `Cooking_FeedLateTime_Avg_RUB`        Nullable(Float32),
    `Cooking_CookingLateTime_Avg`         Nullable(Float32),
    `Cooking_GuestWaitTime_Avg_RUB`       Nullable(Float32),
    `Cooking_ServeTime_Avg_RUB`           Nullable(Float32),
    `Cooking_CookingDuration_Avg_RUB`     Nullable(Float32),
    `Cooking_Cooking1Duration_Avg_RUB`    Nullable(Float32),
    `Cooking_Cooking2Duration_Avg_RUB`    Nullable(Float32),
    `Cooking_Cooking3Duration_Avg_RUB`    Nullable(Float32),
    `Cooking_Cooking4Duration_Avg_RUB`    Nullable(Float32),
    `Cooking_KitchenTime_Avg_RUB`         Nullable(Float32),
    `DishDiscountSumInt_RUB`              Nullable(Float32)
)
ENGINE = MergeTree
PARTITION BY toYYYYMM(OpenDate_Typed)
ORDER BY (OpenDate_Typed, Department, DishGroup, DishId)
SETTINGS index_granularity = 8192;

INSERT INTO fobo.pl6_new SELECT * FROM fobo.pl6;
RENAME TABLE fobo.pl6 TO fobo.pl6_old, fobo.pl6_new TO fobo.pl6;
-- После проверки: DROP TABLE fobo.pl6_old;


-- ─────────────────────────────────────────────────────────────────────────────
-- Проверка после миграции
-- ─────────────────────────────────────────────────────────────────────────────

-- Сравнить количество строк (должно совпасть):
-- SELECT 'pl1_old' as t, count() FROM fobo.pl1_old
-- UNION ALL SELECT 'pl1', count() FROM fobo.pl1
-- UNION ALL SELECT 'pl5_old', count() FROM fobo.pl5_old
-- UNION ALL SELECT 'pl5', count() FROM fobo.pl5
-- UNION ALL SELECT 'pl6_old', count() FROM fobo.pl6_old
-- UNION ALL SELECT 'pl6', count() FROM fobo.pl6;

-- Проверить партиции:
-- SELECT partition, rows, bytes_on_disk FROM system.parts
-- WHERE database = 'fobo' AND table IN ('pl1','pl5','pl6') AND active = 1
-- ORDER BY table, partition;
