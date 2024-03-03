import asyncio
import argparse
import logging
import os
import requests
import sqlite3
from datetime import datetime
from bs4 import BeautifulSoup

# 获取当前工作目录
cwd = os.getcwd()

# 创建或打开名为 github2.db 的数据库
conn = sqlite3.connect(os.path.join(cwd, 'github2.db'))
c = conn.cursor()

# 创建表来存储项目信息
# 创建一个名为 "user" 的表，其中包含以下列：
c.execute('''CREATE TABLE IF NOT EXISTS user (
    用户名 TEXT PRIMARY KEY,  -- 用户名，为主键
    令牌 TEXT                 -- 令牌
)''')

# 创建表来存储项目信息
# 创建一个名为 "repos" 的表，其中包含以下列：
c.execute('''CREATE TABLE IF NOT EXISTS repos (
    仓库名称 TEXT PRIMARY KEY,  -- 仓库名称，为主键
    网址 TEXT,               -- 网址：文本类型
    更新时间 DATETIME     -- 更新时间：日期时间类型
)''')

# 创建另一个名为 "fork" 的表，其中包含以下列：
c.execute('''CREATE TABLE IF NOT EXISTS fork (
    仓库名称 TEXT PRIMARY KEY,           -- 仓库名称：文本类型，为主键
    网址 TEXT,                             -- 网址：文本类型
    更新时间 DATETIME,                 -- 更新时间：日期时间类型
    描述 TEXT,                    -- 描述：文本类型
    星星 TEXT,            -- 星星：文本类型
    复刻 TEXT                 -- 复刻：文本类型
)''')

# 创建索引以提高查询速度
c.execute("CREATE INDEX IF NOT EXISTS idx_repos_name ON repos (仓库名称)")
c.execute("CREATE INDEX IF NOT EXISTS idx_fork_repo_name ON fork (仓库名称)")

# 检查 user 表中是否有任何行
c.execute("SELECT COUNT(*) FROM user")
count = c.fetchone()[0]

# 如果表不为空，则执行查询
if count > 0:
    rows = c.execute("SELECT 用户名, 令牌 FROM user").fetchall()
    print("登录成功！")
else:
    # 如果表为空，则提示用户输入凭据
    while True:
        try:
            username = input("请输入您的 GitHub 用户名：")

            # 检查用户名是否存在
            response = requests.get(f"https://github.com/{username}")
            if response.status_code != 200:
                print("用户名不存在，请重试。")
                continue

            token = input("请输入您的 GitHub 令牌：")

            # 检查令牌是否有效
            response = requests.get("https://api.github.com/user", headers={"Authorization": f"token {token}"})
            if response.status_code != 200:
                print("令牌无效，请重试。")
                continue

            # 将凭据插入到 user 表中
            c.execute("INSERT INTO user (用户名, 令牌) VALUES (?, ?)", (username, token))
            conn.commit()

            # 再次查询 user 表以获取凭据
            rows = c.execute("SELECT 用户名, 令牌 FROM user").fetchall()
            print("登录成功！")
            break
        except sqlite3.IntegrityError as e:
            if "UNIQUE constraint failed: user.用户名" in str(e):
                print("用户名已存在，请使用其他用户名。")
            elif "UNIQUE constraint failed: user.令牌" in str(e):
                print("令牌已存在，请使用其他令牌。")
            else:
                print("未知错误，请重试。")

# 获取用户凭据
def get_user_credentials():
    """获取用户凭据。

    从 user 表中获取用户名和令牌。如果表为空，则提示用户输入凭据。
    """
    with conn:
        c.execute("SELECT 用户名, 令牌 FROM user")
        rows = c.fetchall()
    if not rows:
        username = input("请输入您的 GitHub 用户名：")

        # 检查用户名是否存在
        response = requests.get(f"https://github.com/{username}")
        if response.status_code != 200:
            print("用户名不存在，请重试。")
            return None

        token = input("请输入您的 GitHub 令牌：")

        # 检查令牌是否有效
        response = requests.get("https://api.github.com/user", headers={"Authorization": f"token {token}"})
        if response.status_code != 200:
            print("令牌无效，请重试。")
            return None

        # 将凭据插入到 user 表中
        c.execute("INSERT INTO user (用户名, 令牌) VALUES (?, ?)", (username, token))
        conn.commit()

        # 再次查询 user 表以获取凭据
        rows = c.execute("SELECT 用户名, 令牌 FROM user").fetchall()
    return rows

# 获取用户仓库信息
async def get_user_repos(username, token):
    """获取用户仓库信息。

    使用给定的用户名和令牌从 GitHub API 获取用户仓库信息。
    """
    # 使用 requests 库发送 GET 请求，获取用户仓库信息
    response = requests.get('https://api.github.com/user/repos?per_page=100', auth=(username, token))

    # 检查响应状态码
    if response.status_code != 200:
        logging.error("无法获取用户仓库信息。")
        return None

    # 解析响应内容
    repos = response.json()

    # 创建一个列表来存储仓库信息
    repo_list = []

    # 遍历仓库列表
    for repo in repos:
        # 获取仓库信息
        name = repo['name']
        url = repo['html_url']
        updated_at = datetime.strptime(repo['updated_at'], '%Y-%m-%dT%H:%M:%SZ').strftime('%Y-%m-%d %H:%M:%S')

        # 将仓库信息添加到列表中
        repo_list.append((name, url, updated_at))

    # 使用 `executemany()` 方法一次性插入多行数据
    with conn:
        c.executemany("INSERT OR IGNORE INTO repos (仓库名称, 网址, 更新时间) VALUES (?, ?, ?)", repo_list)

    # 获取每个仓库的详细信息
    tasks = []
    for repo_name in [repo['name'] for repo in repos]:
        task = asyncio.create_task(get_repo_info(repo_name))
        tasks.append(task)

    await asyncio.gather(*tasks)

# 获取仓库信息
async def get_repo_info(repo_name):
    """获取仓库信息。

    使用给定的仓库名称从 GitHub API 获取仓库信息。
    """
    # 设置请求头
    headers = {
        'Authorization': f'token {token}',
        'User-Agent': f'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/108.0.0.0 Safari/537.36'
    }

    # 构建搜索URL
    search_url = f"https://api.github.com/search/repositories?q={repo_name}"

    # 发送搜索请求
    response = requests.get(search_url, headers=headers)

    # 解析搜索结果
    data = response.json()

    # 检查 `data` 中是否存在 `items` 键
    if 'items' not in data:
        # 如果不存在，则打印一条消息
        print(f"没有找到仓库 {repo_name} 的搜索结果")
        return None

    # 获取第一个搜索结果
    result = data['items'][0]

    # 获取搜索结果的URL
    result_url = result['html_url']

    # 获取更新时间
    updated_at = datetime.strptime(result['updated_at'], '%Y-%m-%dT%H:%M:%SZ').strftime('%Y-%m-%d %H:%M:%S')

    # 获取项目名称
    project_name = result['name']

    # 获取项目描述
    description = result['description']

    # 获取星星数
    stars = result['stargazers_count']

    # 获取 fork 数
    forks = result['forks_count']

    # 将仓库信息存储在字典中
    repo_info = {
        'result_url': result_url,
        'updated_at': updated_at,
        'description': description,
        'stars': stars,
        'forks': forks
    }

    # 将仓库详细信息插入到 fork 表中
    with conn:
        c.execute("INSERT OR REPLACE INTO fork (仓库名称, 网址, 更新时间, 描述, 星星, 复刻) VALUES (?, ?, ?, ?, ?, ?)",
                  (repo_name, repo_info['result_url'], repo_info['updated_at'], repo_info['description'], repo_info['stars'], repo_info['forks']))

# 主函数
if __name__ == "__main__":
    # 获取用户凭据
    rows = get_user_credentials()
    if not rows:
        print("无法获取用户凭据。")
        exit(1)
    username, token = rows[0]

    # 获取用户仓库信息
    asyncio.run(get_user_repos(username, token))

    # 从数据库中获取仓库信息
    with conn:
        c.execute("SELECT * FROM repos, fork WHERE repos.仓库名称 = fork.仓库名称")
        rows = c.fetchall()

    # 将仓库信息写入 Markdown 文件
    with open('repos.md', 'w') as f:
        f.write('# GitHub 仓库信息\n\n')
        for row in rows:
            f.write(f'- [{row[0]}]({row[1]}) - {row[2]} - {row[3]} - {row[4]} - {row[5]}\n')

    # 关闭数据库连接
    conn.close()

# 这个代码根据上面的建议进行了以下优化：

# 在 `repos` 和 `fork` 表上创建了索引，以提高查询速度。
# 在 `get_user_repos()` 函数中，使用 `executemany()` 方法一次性插入多行数据，以提高效率。
# 在 `get_repo_info()` 函数中，使用 `INSERT OR REPLACE` 语句来更新或插入仓库信息，以避免重复插入。
# 将up表给成fork表
# 将英文单词翻译成中文
# 修改了错误，将 `网址` 改为 `url`
# 将 `stargazers_count` 改为 `星星`
# 将 `forks_count` 改为 `复刻`

