"""测试设计引擎：策略化实现等价类/边界值/场景法。

统一接口：DesignStrategy.generate(item) -> list[TestCase]
后续追加判定表/因果图/正交实验时，只需新增策略类并注册。
"""