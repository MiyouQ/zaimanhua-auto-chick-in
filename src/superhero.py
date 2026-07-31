import hashlib
import random
import sys
import time

import requests

# 修复 Windows 控制台中文乱码问题
if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
if hasattr(sys.stderr, "reconfigure"):
    try:
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass

from auto_login import get_valid_cookie
from comment_plus import COMMENTS
from utils import (
    get_all_cookies,
    extract_user_info_from_cookies,
    get_task_list,
    extract_tasks_from_response,
    claim_task_reward,
)

ACTIVITY_BASE = "https://activity.zaimanhua.com/dApi"
READ_API_BASE = "https://v4api.zaimanhua.com/app/v1"
V4_API_BASE = "https://v4api.zaimanhua.com"
SPECIAL_TOPIC_ID = 599
SPECIAL_TOPIC_PAGE = "https://zt.zaimanhua.com/details?id=599"
SIGN_KEY = "vN4kj_31721!Wt$"
CHANNEL = "h5"

BLESSING_CONTENTS = COMMENTS

USER_AGENT = ('Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 '
              '(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36')


def make_sign_params():
    """生成带签名的请求参数 (channel, timestamp, sign)"""
    timestamp = int(time.time() * 1000)
    sign = hashlib.md5(f"{CHANNEL}{timestamp}{SIGN_KEY}".encode()).hexdigest()
    return {"channel": CHANNEL, "timestamp": timestamp, "sign": sign}


def build_headers(token):
    """构造请求头"""
    return {
        "Authorization": f"Bearer {token}",
        "User-Agent": USER_AGENT,
        "Referer": "https://activity.zaimanhua.com/superhero/",
        "Accept": "application/json, text/plain, */*",
        "Content-Type": "application/json",
    }


def api_get(token, path, params=None):
    """发起带签名的 GET 请求，返回 JSON 或 None"""
    p = make_sign_params()
    if params:
        p.update(params)
    try:
        resp = requests.get(f"{ACTIVITY_BASE}{path}",
                            headers=build_headers(token),
                            params=p, timeout=15)
        if resp.status_code == 200:
            return resp.json()
        print(f"    [HTTP {resp.status_code}]")
    except Exception as e:
        print(f"    请求异常: {e}")
    return None


def api_post(token, path, data=None):
    """发起带签名的 POST 请求，返回 JSON 或 None"""
    p = make_sign_params()
    try:
        resp = requests.post(f"{ACTIVITY_BASE}{path}?{_urlencode(p)}",
                             headers=build_headers(token),
                             json=data or {}, timeout=15)
        if resp.status_code == 200:
            return resp.json()
        print(f"    [HTTP {resp.status_code}]")
    except Exception as e:
        print(f"    请求异常: {e}")
    return None


def _urlencode(params):
    """将参数字典编码为 query string"""
    from urllib.parse import urlencode
    return urlencode(params)


def get_activity_status(token):
    """查询活动状态 (draw_load)

    返回 dict: times(抽奖次数), shareTimes/readTimes/addComTimes(任务状态),
               userInfo, records
    """
    result = api_get(token, "/draw/draw_load")
    if not result or result.get("errno") != 0:
        errmsg = result.get("errmsg", "未知错误") if result else "无法连接"
        print(f"  查询活动状态失败: {errmsg}")
        return None
    return result.get("data", {})


def do_share_task(token):
    """执行分享任务，返回是否成功"""
    result = api_get(token, "/draw/share")
    if not result:
        return False
    if result.get("errno") == 0:
        print("  [v] 分享任务完成! 抽奖次数 +1")
        return True
    print(f"  分享任务失败: {result.get('errmsg', '')}")
    return False


def do_comment_task(token):
    """执行评论任务，返回是否成功"""
    content = random.choice(BLESSING_CONTENTS)
    result = api_post(token, "/draw/add_comment", {"con": content, "source": 2})
    if not result:
        return False
    if result.get("errno") == 0:
        print(f"  [v] 评论发送成功! 内容: {content}")
        return True
    print(f"  评论任务失败: {result.get('errmsg', '')}")
    return False


def do_draw(token):
    """执行一次抽奖，返回 (是否成功, 奖品信息 dict)"""
    result = api_get(token, "/draw/drawing")
    if not result:
        return False, None
    if result.get("errno") == 0:
        data = result.get("data", {})
        prize = data.get("prize", {}) if isinstance(data, dict) else {}
        return True, {
            "id": data.get("id"),
            "cate": prize.get("cate"),
            "name": prize.get("name"),
        }
    print(f"    抽奖失败: {result.get('errmsg', '')}")
    return False, None


class SuperheroReader:
    """轻量版阅读器：从活动指定专题随机选漫画，读取前 2 页以完成任务"""

    def __init__(self, token, debug=False):
        self.token = token
        self.debug = debug
        self.headers = {
            "Authorization": f"Bearer {token}",
            "User-Agent": "okhttp/4.9.3",
            "Accept": "application/json, text/plain, */*",
        }

    def _get(self, path, params=None):
        try:
            resp = requests.get(f"{READ_API_BASE}{path}", headers=self.headers,
                                params=params, timeout=15)
            if resp.status_code == 200:
                return resp.json()
        except Exception as e:
            if self.debug:
                print(f"  [DEBUG] 请求异常: {e}")
        return None

    def _get_comic_list(self):
        """从活动指定的专题获取漫画列表"""
        try:
            resp = requests.get(
                f"{V4_API_BASE}/api/v1/zt/h5/detail",
                headers=self.headers,
                params={"id": SPECIAL_TOPIC_ID},
                timeout=15,
            )
            if resp.status_code == 200:
                data = resp.json()
                if isinstance(data, dict) and data.get("errno") == 0:
                    raw = data.get("data", {}).get("comicList", []) or []
                    comics = []
                    for item in raw:
                        if isinstance(item, dict):
                            comic_id = item.get("comic_id") or item.get("id")
                            if comic_id:
                                comics.append({
                                    "id": comic_id,
                                    "name": item.get("name") or item.get("title")
                                    or "未知漫画",
                                })
                    return comics
        except Exception as e:
            if self.debug:
                print(f"  [DEBUG] 获取专题漫画异常: {e}")
        return []

    def _get_chapters(self, comic_id):
        data = self._get(f"/comic/detail/{comic_id}", {"_v": "2.2.5"})
        if not data or data.get("errno") != 0:
            return []
        comic_info = data.get("data", {}).get("data", {})
        chapters = []
        for volume in (comic_info.get("chapters") or []):
            if isinstance(volume, dict) and isinstance(volume.get("data"), list):
                for ch in volume["data"]:
                    if ch.get("canRead", True) and ch.get("chapter_id"):
                        chapters.append(ch)
        return chapters

    def read(self, max_attempts=8):
        """从活动专题随机选漫画阅读前2页，返回是否完成"""
        comics = self._get_comic_list()
        if not comics:
            print("  未获取到漫画列表")
            return False

        random.shuffle(comics)
        attempted = 0
        for comic in comics:
            if attempted >= max_attempts:
                break
            comic_id, comic_name = comic["id"], comic.get("name") or "未知漫画"
            print(f"  随机选中漫画: {comic_name} (ID: {comic_id})")

            chapters = self._get_chapters(comic_id)
            if not chapters:
                print(f"  该漫画无可用章节，换一本重试...")
                attempted += 1
                continue

            chapter = random.choice(chapters)
            chapter_id = chapter.get("chapter_id")
            chapter_title = chapter.get("chapter_title") or chapter.get("title") or f"第{chapter_id}话"
            print(f"  随机选中章节: {chapter_title} (ID: {chapter_id})")

            data = self._get(f"/comic/chapter/{comic_id}/{chapter_id}", {"_v": "2.2.5"})
            images = []
            if data and data.get("errno") == 0:
                inner = data.get("data", {}).get("data", {})
                images = (inner.get("page_url_hd") or inner.get("page_url")
                          or inner.get("images") or [])

            if not images:
                print(f"  无法获取章节图片，换一本重试...")
                attempted += 1
                continue

            pages_read = 0
            for img_url in images[:2]:
                try:
                    resp = requests.get(img_url, headers=self.headers, timeout=15)
                    if resp.status_code == 200:
                        pages_read += 1
                except Exception:
                    pass

            print(f"  [v] 阅读完成! 读了 {pages_read} 页")
            return pages_read > 0

        print("  尝试多本漫画后仍无可读章节")
        return False


def run_read_task(cookie_str):
    """执行阅读任务"""
    print(f"\n--- 执行阅读任务 (专题: {SPECIAL_TOPIC_PAGE}) ---")
    user_info = extract_user_info_from_cookies(cookie_str)
    token = user_info.get("token") if isinstance(user_info, dict) else None
    if not token:
        print("  无法获取 token，跳过阅读任务")
        return False
    reader = SuperheroReader(token)
    return reader.read()


def run_draw_lottery(token, draw_count):
    """根据抽奖次数循环抽奖，返回抽奖结果列表"""
    if draw_count <= 0:
        print("  当前无可抽奖次数")
        return []

    print(f"\n=== 开始抽奖 (剩余 {draw_count} 次) ===")
    results = []
    for i in range(1, draw_count + 1):
        print(f"\n--- 第 {i}/{draw_count} 次抽奖 ---")
        success, prize = do_draw(token)
        if success and prize:
            prize_name = prize.get("name") or "谢谢参与"
            prize_cate = prize.get("cate")
            print(f"  [v] 抽奖成功!")
            if prize_cate and prize_cate > 0:
                print(f"      奖品: {prize_name} (类别: {prize_cate}, ID: {prize.get('id')})")
            else:
                print(f"      结果: {prize_name}")
            results.append(prize)
        else:
            print("  抽奖未成功")
        time.sleep(1)

    return results


def has_vip_prize(results):
    """判断抽奖结果中是否包含"漫画VIP"类奖品"""
    if not results:
        return False
    for prize in results:
        name = (prize.get("name") or "") if isinstance(prize, dict) else ""
        if "VIP" in name.upper():
            return True
    return False


def claim_personal_center_tasks(token):
    """领取个人中心所有可领取的任务奖励，防止VIP积分少领"""
    print("\n--- 检查个人中心任务并领取可领取的奖励 ---")
    task_result = get_task_list(token)
    if not task_result or task_result.get("errno") != 0:
        print("  获取任务列表失败")
        return False

    tasks = extract_tasks_from_response(task_result)
    claimed = 0
    failed = 0
    for task in tasks:
        task_id = task.get("id") or task.get("taskId")
        task_name = task.get("title") or task.get("name") or task.get("taskName", "未知")
        status = task.get("status", 0)
        if status == 2 and task_id:
            print(f"  领取任务: {task_name} (ID: {task_id})")
            success, result = claim_task_reward(token, task_id)
            if success:
                print(f"    [OK] 领取成功")
                claimed += 1
            else:
                print(f"    [FAIL] 领取失败")
                failed += 1

    if claimed == 0 and failed == 0:
        print("  没有可领取的奖励")
    else:
        print(f"  领取完成: 成功 {claimed} 个, 失败 {failed} 个")
    return failed == 0


def print_draw_summary(results):
    """输出抽奖结果汇总"""
    print("\n" + "=" * 60)
    print("  抽奖结果汇总")
    print("=" * 60)
    if not results:
        print("  本轮没有获得任何奖品")
    else:
        print(f"  本轮抽奖获得 {len(results)} 个奖品:")
        for i, prize in enumerate(results, 1):
            prize_name = prize.get("name") or "谢谢参与"
            prize_cate = prize.get("cate")
            if prize_cate and prize_cate > 0:
                print(f"    {i}. {prize_name} (类别: {prize_cate})")
            else:
                print(f"    {i}. {prize_name}")
    print("=" * 60)


def run_account(index, name, cookie_str):
    """为单个账号执行活动任务并抽奖"""
    print(f"\n{'=' * 60}")
    print(f"  账号: {name}")
    print(f"{'=' * 60}")

    valid_cookie, _ = get_valid_cookie(
        cookie_str, name, account_index=index if index > 0 else None
    )
    if not valid_cookie:
        print("[ERROR] 无法获取有效 Cookie")
        return False
    cookie_str = valid_cookie

    user_info = extract_user_info_from_cookies(cookie_str)
    token = user_info.get("token") if isinstance(user_info, dict) else None
    if not token:
        print("[ERROR] 无法获取 token")
        return False

    print("\n=== 活动状态 ===")
    status = get_activity_status(token)
    if not status:
        return False

    draw_count = status.get("times", 0)
    share_done = status.get("shareTimes", 0) >= 1
    read_done = status.get("readTimes", 0) >= 1
    comment_done = status.get("addComTimes", 0) >= 1

    print(f"  抽奖次数: {draw_count}")
    print(f"  分享任务: {'已完成' if share_done else '未完成'}")
    print(f"  阅读任务: {'已完成' if read_done else '未完成'}")
    print(f"  评论任务: {'已完成' if comment_done else '未完成'}")

    if not share_done:
        print("\n--- 执行分享任务 ---")
        if do_share_task(token):
            draw_count += 1
            time.sleep(1)

    if not comment_done:
        print("\n--- 执行祝福评论任务 ---")
        if do_comment_task(token):
            draw_count += 1
            time.sleep(1)

    if not read_done:
        if run_read_task(cookie_str):
            draw_count += 1
            time.sleep(1)

    print("\n--- 任务完成，重新查询活动状态 ---")
    status = get_activity_status(token)
    if status:
        draw_count = status.get("times", draw_count)
        print(f"\n=== 活动状态 ===")
        print(f"  抽奖次数: {draw_count}")
        print(f"  分享任务: {'已完成' if status.get('shareTimes', 0) >= 1 else '未完成'}")
        print(f"  阅读任务: {'已完成' if status.get('readTimes', 0) >= 1 else '未完成'}")
        print(f"  评论任务: {'已完成' if status.get('addComTimes', 0) >= 1 else '未完成'}")

    results = run_draw_lottery(token, draw_count)
    print_draw_summary(results)

    # 若抽奖奖品中包含"漫画VIP"，检查个人中心任务并领取，防止VIP积分少领
    if has_vip_prize(results):
        print("\n检测到抽奖获得漫画VIP，开始检查个人中心任务...")
        claim_personal_center_tasks(token)

    return True


def main():
    """主函数，支持多账号"""
    cookies_list = get_all_cookies()
    if not cookies_list:
        print("Error: 未配置任何账号 Cookie")
        print("请设置 ZAIMANHUA_COOKIE 或 ZAIMANHUA_USERNAME/ZAIMANHUA_PASSWORD 环境变量")
        return False

    print(f"共发现 {len(cookies_list)} 个账号")

    all_success = True
    for index, (name, cookie_str) in enumerate(cookies_list):
        ok = run_account(index, name, cookie_str)
        if not ok:
            all_success = False
        if index < len(cookies_list) - 1:
            print("\n等待 5 秒后切换下一个账号...")
            time.sleep(5)

    print(f"\n{'=' * 60}")
    if all_success:
        print("所有账号超级英雄活动执行完成！")
    else:
        print("部分账号活动执行失败，请检查日志")
    print("=" * 60)
    return all_success


if __name__ == '__main__':
    success = main()
    exit(0 if success else 1)
