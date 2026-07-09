import random
import requests
import argparse
from utils import (
    get_all_cookies,
    extract_user_info_from_cookies,
    claim_task_reward,
)

# 配置
API_BASE = "https://v4api.zaimanhua.com/app/v1"
USER_AGENT = 'okhttp/4.9.3'

# 阅读参数
RANDOM_COMIC_COUNT = 5   # 随机选择漫画数量
READ_PAGE_COUNT = 2      # 每本漫画阅读页数
READ_TASK_ID = 13        # 阅读任务ID (海螺小姐)


class ZaimanhuaReader:
    """在漫画阅读器 - 支持获取多源漫画并随机阅读"""

    def __init__(self, cookie_str, debug=False):
        self.cookie_str = cookie_str
        self.user_info = extract_user_info_from_cookies(cookie_str)
        self.token = self.user_info.get('token')
        self.debug = debug
        self.headers = {
            'Authorization': f'Bearer {self.token}',
            'User-Agent': USER_AGENT,
            'Accept': 'application/json, text/plain, */*',
        }

    def get_token(self):
        return self.token

    def check_read_task_status(self):
        """检查阅读任务状态，返回 (status_code, status_desc)

        状态值: 1=未完成, 2=可领取, 3=已完成(奖励已领), None=无法获取
        """
        url = "https://i.zaimanhua.com/lpi/v1/task/list"
        try:
            resp = requests.get(url, headers=self.headers, timeout=10)
            if resp.status_code == 200:
                data = resp.json()
                if data.get('errno') == 0:
                    task_data = data.get('data', {}).get('task', {})
                    tasks = []
                    if isinstance(task_data, dict):
                        tasks.extend(task_data.get('dayTask', []) or [])
                        tasks.extend(task_data.get('newUserTask', []) or [])
                    for task in tasks:
                        if task.get('id') == READ_TASK_ID or task.get('taskId') == READ_TASK_ID:
                            return task.get('status')
            return None
        except Exception as e:
            if self.debug:
                print(f"  [DEBUG] 检查任务状态异常: {e}")
            return None

    def _request(self, url, params=None):
        """通用请求方法"""
        try:
            resp = requests.get(url, headers=self.headers, params=params, timeout=15)
            if resp.status_code == 200:
                data = resp.json()
                if data.get('errno') == 0:
                    return data.get('data')
                elif self.debug:
                    print(f"  [DEBUG] API 错误: {data.get('errmsg')}")
            elif self.debug:
                print(f"  [DEBUG] HTTP 错误: {resp.status_code}")
        except Exception as e:
            if self.debug:
                print(f"  [DEBUG] 请求异常: {e}")
        return None

    def get_home_comics(self, page=1, size=20):
        """获取首页/推荐漫画（人气排序）"""
        params = {
            'sortType': '2',     # 人气排序
            'status': '0',       # 全部
            'cate': '0',         # 全部
            'zone': '0',         # 全部
            'theme': '0',        # 全部
            'page': str(page),
            'size': str(size),
        }
        data = self._request(f"{API_BASE}/comic/filter/list", params)
        if isinstance(data, dict):
            raw = data.get('comicList') or data.get('list') or []
            # 统一字段名：filter/list 返回 id/name，其他接口返回 comic_id/title
            normalized = []
            for item in raw:
                if isinstance(item, dict):
                    normalized.append({
                        'comic_id': item.get('comic_id') or item.get('id'),
                        'title': item.get('title') or item.get('name'),
                        'cover': item.get('cover'),
                        'authors': item.get('authors'),
                        'status': item.get('status'),
                        'types': item.get('types'),
                    })
            return normalized
        elif isinstance(data, list):
            return data
        return []

    def get_rank_comics(self, page=1, size=20):
        """获取排行榜漫画"""
        params = {
            'tag_id': '0',
            'by_time': '',       # 总排行
            'rank_type': '0',    # 人气排序
            'page': str(page),
        }
        data = self._request(f"{API_BASE}/comic/rank/list", params)
        if isinstance(data, list):
            return data
        return []

    def get_recent_updates(self, page=1, size=20):
        """获取最近更新漫画"""
        data = self._request(f"{API_BASE}/comic/update/list/0/{page}")
        if isinstance(data, list):
            return data
        return []

    def get_all_source_comics(self):
        """获取首页 + 排行榜 + 最近更新的漫画，去重后返回"""
        all_comics = []
        seen_ids = set()

        sources = [
            ("首页推荐", self.get_home_comics()),
            ("排行榜", self.get_rank_comics()),
            ("最近更新", self.get_recent_updates()),
        ]

        for source_name, comics in sources:
            if self.debug:
                print(f"  [DEBUG] {source_name}: 获取到 {len(comics)} 本漫画")
            for comic in comics:
                comic_id = comic.get('comic_id') or comic.get('id')
                if comic_id and comic_id not in seen_ids:
                    seen_ids.add(comic_id)
                    comic['_source'] = source_name
                    all_comics.append(comic)

        if self.debug:
            print(f"  [DEBUG] 去重后共 {len(all_comics)} 本漫画")
        return all_comics

    def get_chapter_list(self, comic_id):
        """获取漫画的章节列表

        API 响应: { errno: 0, data: { data: { id, chapters: [...], canRead }, readingRecord } }
        _request() 已剥离外层 data，返回的是 { data: {id, chapters, ...}, readingRecord }
        所以需要再取 .data 才能拿到真正的详情对象
        """
        params = {'_v': '2.2.5'}
        data = self._request(f"{API_BASE}/comic/detail/{comic_id}", params)
        if not data or not isinstance(data, dict):
            return []

        # _request 返回外层 data → 取 .data 得到漫画详情
        comic_info = data.get('data', {})
        if not isinstance(comic_info, dict):
            return []

        volumes = comic_info.get('chapters') or []

        all_chapters = []
        if isinstance(volumes, list):
            for volume in volumes:
                if isinstance(volume, dict) and 'data' in volume:
                    chapter_list = volume['data']
                    if isinstance(chapter_list, list):
                        for ch in chapter_list:
                            if ch.get('canRead', True):
                                all_chapters.append(ch)
        return all_chapters

    def get_chapter_images(self, comic_id, chapter_id):
        """获取章节的图片列表（用于翻页阅读）

        实际 API 响应结构:
        { errno: 0, data: { data: { page_url_hd: [...], page_url: [...], canRead, ... } } }
        """
        params = {'_v': '2.2.5'}
        headers = {**self.headers, 'Platform': 'h5'}
        try:
            resp = requests.get(
                f"{API_BASE}/comic/chapter/{comic_id}/{chapter_id}",
                headers=headers, params=params, timeout=15
            )
            if resp.status_code == 200:
                data = resp.json()
                if data.get('errno') == 0:
                    # _request 会返回外层 data，这里直接解析
                    inner = data.get('data', {})
                    chapter_data = inner.get('data', {}) if isinstance(inner, dict) else {}
                    images = (chapter_data.get('page_url_hd')
                              or chapter_data.get('page_url')
                              or chapter_data.get('images'))
                    return images or []
        except Exception as e:
            if self.debug:
                print(f"  [DEBUG] 获取图片失败: {e}")
        return []

    def read_random_comics(self):
        """核心逻辑：检查任务状态 -> 获取多源漫画 -> 随机选本 -> 随机选章 -> 读取图片"""
        status = self.check_read_task_status()
        if status == 3:
            print("  阅读任务已完成 (status=3)，跳过")
            return True
        if status == 2:
            print("  阅读任务可领取 (status=2)，尝试领取...")
            success, _ = claim_task_reward(self.token, READ_TASK_ID)
            if success:
                print("  [OK] API 领取成功")
                return True
            print("  API 领取失败，尝试 UI 领取...")

        print("\n--- 开始获取漫画列表 ---")

        all_comics = self.get_all_source_comics()
        if not all_comics:
            print("  未找到任何漫画")
            return False

        print(f"  共获取到 {len(all_comics)} 本漫画（已去重）")

        select_count = min(RANDOM_COMIC_COUNT, len(all_comics))
        selected_comics = random.sample(all_comics, select_count)
        random.shuffle(selected_comics)
        print(f"  随机选择了 {select_count} 本漫画")

        total_pages_read = 0
        success_count = 0

        for idx, comic in enumerate(selected_comics, 1):
            comic_id = comic.get('comic_id') or comic.get('id')
            comic_name = comic.get('title') or comic.get('name') or '未知漫画'
            source = comic.get('_source', '')

            print(f"\n  [{idx}/{select_count}] 《{comic_name}》(ID:{comic_id}) [{source}]")

            chapters = self.get_chapter_list(comic_id)
            if not chapters:
                print(f"    无可用章节，跳过")
                continue

            chapter = random.choice(chapters)
            chapter_id = chapter.get('chapter_id')
            chapter_title = chapter.get('chapter_title') or chapter.get('title') or f"第{chapter_id}章"

            print(f"    选择章节: {chapter_title} (ID:{chapter_id})")

            images = self.get_chapter_images(comic_id, chapter_id)
            if not images:
                print(f"    无法获取图片，跳过")
                continue

            read_count = min(READ_PAGE_COUNT, len(images))
            print(f"    章节共 {len(images)} 页，将阅读前 {read_count} 页")

            for page_idx in range(read_count):
                img_url = images[page_idx]
                try:
                    resp = requests.get(img_url, headers=self.headers, timeout=15)
                    if resp.status_code == 200:
                        total_pages_read += 1
                        if self.debug:
                            print(f"      第{page_idx + 1}页读取成功 ({len(resp.content)} bytes)")
                    else:
                        if self.debug:
                            print(f"      第{page_idx + 1}页 HTTP {resp.status_code}")
                except Exception as e:
                    if self.debug:
                        print(f"      第{page_idx + 1}页异常: {e}")

            print(f"    [OK] 完成，已阅读 {read_count} 页")
            success_count += 1

        print(f"\n--- 阅读结束 ---")
        print(f"  处理漫画: {select_count} 本，成功: {success_count} 本，总阅读页数: {total_pages_read}")
        return success_count > 0


def run_auto_read():
    parser = argparse.ArgumentParser(description='Zaimanhua Auto Read Script')
    parser.add_argument('--debug', action='store_true', help='开启调试日志')
    args = parser.parse_args()

    cookies_list = get_all_cookies()
    if not cookies_list:
        print("未发现 Cookie 记录。")
        return False

    for index, (label, cookie_str) in enumerate(cookies_list):
        print(f"\n{'='*60}")
        print(f"账号: {label}")
        print(f"{'='*60}")

        from auto_login import get_valid_cookie
        valid_cookie, is_auto_login = get_valid_cookie(cookie_str, label, account_index=index if index > 0 else None)

        if not valid_cookie:
            print(f"[ERROR] 无法获取有效Cookie")
            continue

        if is_auto_login:
            print(f"  [v] 使用自动登录获取的新Cookie")
            cookie_str = valid_cookie
        else:
            print(f"  [v] 使用配置的Cookie")

        reader = ZaimanhuaReader(cookie_str, debug=args.debug)
        token = reader.get_token()
        if not token:
            print("Token 无效，跳过该账号。")
            continue

        # 执行随机阅读
        reader.read_random_comics()

    return True


if __name__ == "__main__":
    success = run_auto_read()
    exit(0 if success else 1)
