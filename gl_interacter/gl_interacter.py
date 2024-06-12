from flask import Flask, request, jsonify, abort
import requests
import os
import urllib.parse  # 用于URL编码
from functools import wraps  # 用于装饰器
from urllib.parse import quote_plus

app = Flask(__name__)

RHINO_API_KEY = os.getenv("RHINO_API_KEY")
GITLAB_DOMAIN = os.getenv('GITLAB_DOMAIN', 'gitlab.com')

def require_api_key(view_function):
    @wraps(view_function)
    def decorated_function(*args, **kwargs):
        if request.headers.get('X-Api-Key') and request.headers.get('X-Api-Key') == RHINO_API_KEY:
            return view_function(*args, **kwargs)
        else:
            abort(401)  # Unauthorized access
    return decorated_function

def check_branch_exists(project_id, branch_name):
    encoded_project_id = quote_plus(project_id)
    gitlab_api_url = f"https://{GITLAB_DOMAIN}/api/v4/projects/{encoded_project_id}/repository/branches/{branch_name}"
    headers = {'Private-Token': os.getenv('GITLAB_PRIVATE_TOKEN')}
    response = requests.get(gitlab_api_url, headers=headers)
    return response.status_code == 200

@app.route('/mr_content', methods=['GET'])
@require_api_key
def get_mr_content():
    project_id = request.args.get('project_id')
    mr_iid = request.args.get('mr_iid')

    if not project_id or not mr_iid:
        return jsonify({'code': 400, 'message': 'Missing project_id or mr_iid'}), 400

    # 先对 project_id 进行编码
    encoded_project_id = quote_plus(project_id)
    
    # 使用project_id构建获取MR基本信息的API URL
    gitlab_api_url = f"https://{GITLAB_DOMAIN}/api/v4/projects/{encoded_project_id}/merge_requests/{mr_iid}"
    headers = {'Private-Token': os.getenv('GITLAB_PRIVATE_TOKEN')}
    response = requests.get(gitlab_api_url, headers=headers)

    if response.status_code != 200:
        return jsonify({'code': response.status_code, 'message': 'Failed to fetch MR info'}), response.status_code

    mr_content = response.json()

    # 构建获取MR的diffs的API URL
    encoded_project_id = quote_plus(project_id)
    diffs_api_url = f"https://{GITLAB_DOMAIN}/api/v4/projects/{encoded_project_id}/merge_requests/{mr_iid}/changes"
    diffs_response = requests.get(diffs_api_url, headers=headers)

    if diffs_response.status_code != 200:
        return jsonify({'code': diffs_response.status_code, 'message': 'Failed to fetch MR diffs'}), diffs_response.status_code

    diffs_content = diffs_response.json()

    # 提取和处理所需的diff数据
    diffs = diffs_content.get('changes', [])
    diff_text = '\n'.join([change.get('diff', '') for change in diffs])

    return jsonify({
        'title': mr_content.get('title'),
        'description': mr_content.get('description'),
        'source_branch': mr_content.get('source_branch'),
        'target_branch': mr_content.get('target_branch'),
        'diffs': diff_text  # 提供完整的diff文本
    })

@app.route('/file_content', methods=['GET'])
@require_api_key
def get_file_content():
    project_id = request.args.get('project_id')
    file_path = request.args.get('file_path')
    branch_name = request.args.get('branch_name')

    if not project_id or not file_path:
        return jsonify({'code': 400, 'message': 'Missing project_id or file_path'}), 400

    if not branch_name:
        # 检查是否存在 main 或 master 分支
        if check_branch_exists(project_id, "main"):
            branch_name = "main"
        elif check_branch_exists(project_id, "master"):
            branch_name = "master"
        else:
            return jsonify({'code': 404, 'message': 'No main or master branch found'}), 404

    # 构建GitLab API的URL
    file_path_encoded = urllib.parse.quote_plus(file_path)
    encoded_project_id = quote_plus(project_id)
    gitlab_api_url = f"https://{GITLAB_DOMAIN}/api/v4/projects/{encoded_project_id}/repository/files/{file_path_encoded}/raw?ref={branch_name}"
    
    headers = {'Private-Token': os.getenv('GITLAB_PRIVATE_TOKEN')}
    response = requests.get(gitlab_api_url, headers=headers)

    if response.status_code != 200:
        return jsonify({'code': response.status_code, 'message': 'Failed to fetch file content'}), response.status_code

    file_content = response.text
    return jsonify({'content': file_content})

@app.route('/issue_info', methods=['GET'])
@require_api_key
def get_issue_info():
    project_id = request.args.get('project_id')  # GitLab使用project_id来识别项目
    issue_iid = request.args.get('issue_iid')  # GitLab中Issue使用内部ID（iid），而不是全局唯一ID

    if not project_id or not issue_iid:
        return jsonify({'code': 400, 'message': 'Missing project_id or issue_iid'}), 400

    # 构建获取Issue信息的GitLab API URL
    encoded_project_id = quote_plus(project_id)
    gitlab_api_url = f"https://{GITLAB_DOMAIN}/api/v4/projects/{encoded_project_id}/issues/{issue_iid}"
    
    # 使用Private-Token进行认证
    headers = {'Private-Token': os.getenv('GITLAB_PRIVATE_TOKEN')}
    response = requests.get(gitlab_api_url, headers=headers)

    if response.status_code != 200:
        return jsonify({'code': response.status_code, 'message': 'Failed to fetch issue info'}), response.status_code

    issue_info = response.json()

    return jsonify({
        'title': issue_info.get('title'),
        'description': issue_info.get('description')
    })

@app.route('/submit_mr_comment', methods=['POST'])  # 注意这里使用'mr'代替'pr'以匹配GitLab的术语
@require_api_key
def submit_mr_comment():
    token = os.getenv('GITLAB_PRIVATE_TOKEN')
    if not token:
        return jsonify({'code': 401, 'message': 'GitLab access token is not set'}), 401

    project_id = request.json.get('project_id')  # 在GitLab中使用project_id
    mr_iid = request.json.get('mr_iid')  # GitLab中Merge Request使用iid
    comment_body = request.json.get('comment_body')

    if not project_id or not mr_iid or not comment_body:
        return jsonify({'code': 400, 'message': 'Missing required parameters'}), 400

    # 构建GitLab API URL来添加评论
    encoded_project_id = quote_plus(project_id)
    comment_url = f"https://{GITLAB_DOMAIN}/api/v4/projects/{encoded_project_id}/merge_requests/{mr_iid}/notes"
    
    headers = {
        'Private-Token': token,
        'Content-Type': 'application/json'
    }

    data = {
        'body': comment_body
    }

    response = requests.post(comment_url, headers=headers, json=data)

    if response.status_code != 201:
        return jsonify({'code': response.status_code, 'message': 'Failed to create comment'}), response.status_code
    return jsonify({'message': 'Comment created successfully'}), 201

@app.route('/repo_structure', methods=['GET'])
@require_api_key
def get_repo_structure():
    project_id = request.args.get('project_id')  # GitLab使用project_id识别项目
    branch_name = request.args.get('branch_name')

    if not project_id:
        return jsonify({'code': 400, 'message': 'Missing project_id'}), 400

    if not branch_name:
        # 检查是否存在 main 或 master 分支
        if check_branch_exists(project_id, "main"):
            branch_name = "main"
        elif check_branch_exists(project_id, "master"):
            branch_name = "master"
        else:
            return jsonify({'code': 404, 'message': 'No main or master branch found'}), 404

    # 构建获取仓库文件和目录的GitLab API URL
    encoded_project_id = quote_plus(project_id)
    gitlab_api_url = f"https://{GITLAB_DOMAIN}/api/v4/projects/{encoded_project_id}/repository/tree?ref={branch_name}&recursive=true"
    
    headers = {'Private-Token': os.getenv('GITLAB_PRIVATE_TOKEN')}
    response = requests.get(gitlab_api_url, headers=headers)

    if response.status_code != 200:
        return jsonify({'code': response.status_code, 'message': 'Failed to get repository structure'}), response.status_code

    items = response.json()
    repo_structure = {'directories': [], 'files': []}

    for item in items:
        if item['type'] == 'tree':  # 在GitLab中，目录类型被标记为'tree'
            repo_structure['directories'].append(item['path'])
        elif item['type'] == 'blob':  # 在GitLab中，文件类型被标记为'blob'
            repo_structure['files'].append(item['path'])

    return jsonify(repo_structure)

if __name__ == '__main__':
    app.run(host="0.0.0.0", port=5000)