# 测试代码规范

所有测例必须能被 `pytest --collect-only` 发现，并在 VSCode 测试面板中可见。

---

## 一、文件结构

```
tests/
├── conftest.py          # 全局配置：日志、fixtures、.env.test 加载
├── test_*.py            # 每个被测模块对应一个文件
.env.test                # 集成测试参数（不提交到 .env）
```

## 二、测例组织方式

```python
# ✅ 正确：用 TestClass 组织相关测例
class Test功能名称:
    """这个类测试什么功能。"""

    def test_具体行为(self):
        """这个测例验证什么。"""
        # ... 测试逻辑 ...
        logger.info("简短的确认信息 ✓")

# ❌ 错误：裸函数、argparse CLI、__main__ 入口
```

**规则**：
- 类名：`Test` + 大驼峰功能描述（如 `TestBrowserNavigation`）
- 方法名：`test_` + 下划线蛇形描述（如 `test_go_back_and_forward`）
- 每个方法必须有 docstring，说明验证内容
- 文件顶部加 `import logging; logger = logging.getLogger(__name__)`
- 每个测例末尾加 `logger.info("... ✓")` — 输出一条简短的确认日志

## 三、日志输出

每个测例执行完成后，必须输出一条 `logger.info()` 确认信息：

```python
logger.info("PageState 默认值验证通过 ✓")
logger.info("[百度] https://www.baidu.com → log/百度_tree_text.txt (2431 字符)")
```

- 日志自动写入 `log/Tests.log`（conftest.py 已配置好）
- 每次运行插入文件顶端，保留历史记录
- **禁止使用 `print()`** — 一律用 `logger.info()`
- **不要输出到终端** — `log_cli` 已关闭

## 四、集成测试

### 4.1 参数通过 .env.test 配置

```env
PERCEPTION_TEST_LABEL_1=百度
PERCEPTION_TEST_URL_1=https://www.baidu.com
LLM_TEST_PROMPT=用一句话介绍你自己
VLM_TEST_PROMPT=请用中文描述这张图片的内容
VLM_TEST_IMAGE=path/to/test_image.png
```

### 4.2 跳过条件

```python
@pytest.mark.skipif(not 条件, reason="原因说明")
@pytest.mark.integration
class Test集成功能:
    @pytest.fixture(autouse=True)
    def check_env(self):
        if not os.getenv("必要变量"):
            pytest.skip("必要变量未设置")
```

### 4.3 多配置参数化

```python
@pytest.mark.parametrize("target", 目标列表, ids=[t[0] for t in 目标列表])
def test_多配置(self, target):
    """..."""
```

## 五、禁止模式

| 禁止写法 | 原因 |
|---------|------|
| `if __name__ == "__main__"` + argparse | VSCode 无法发现这类测例 |
| `print()` 输出调试信息 | 统一用 `logger.info()` |
| 硬编码 API Key / URL | 通过 `.env.test` 环境变量传入 |
| 在测例中使用 `time.sleep()` | 尽量使用 wait 机制 |
| 单元测试和集成测试混在一个方法里 | 各自分开 |

## 六、快速模板

```python
import logging

import pytest

from 被测模块 import 被测类

logger = logging.getLogger(__name__)


class Test被测类:
    """被测类的单元测试。"""

    def test_基本行为(self):
        """验证基本功能正常。"""
        result = 被测类().方法()
        assert result == 期望值
        logger.info("基本行为验证通过 ✓")
```

## 七、运行命令

```powershell
pytest tests/test_你的文件.py -v          # 只跑你的文件
pytest tests/ -v -k "not integration"     # 只跑单元测试
pytest tests/ -v -m integration           # 只跑集成测试
```
