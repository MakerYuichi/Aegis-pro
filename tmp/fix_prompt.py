import re

with open("/app/src/services/github_service.py", "r") as f:
    content = f.read()

# Replace the prompt with a more detailed version
old_prompt = '''prompt = f"""
You are analyzing which PR is most likely to have caused this error.

Error location: {file_path}, line {line_number}

PRs that modified this file or related files:
{json.dumps(pr_list, indent=2)}

Rate each PR's relevance (0-1) with as much precision as possible (e.g., 0.87, 0.93, 0.76). Higher score = more likely to have caused the error.
Return ONLY JSON array with ALL PRs scored. Use exact scores, not rounded to 0.05 increments:
[
    {{"number": 123, "score": 0.87, "reason": "Modified the exact file at the error line"}},
    {{"number": 456, "score": 0.73, "reason": "Modified the same file but different function"}}
]
"""'''

new_prompt = '''prompt = f"""
You are a senior software engineer analyzing which GitHub Pull Request (PR) most likely caused a NullPointerException at line {line_number} in {file_path}.

**Error Context:** A NullPointerException occurred at line {line_number} in {file_path}. This means code tried to access a method/property on a null object.

**PRs that modified this file or related files:**
{json.dumps(pr_list, indent=2)}

**Analyze each PR for:**
1. Did the PR modify the exact file `{file_path}`?
2. Did the PR change code around line {line_number}?
3. Did the PR remove/add a null check?
4. Did the PR change data structures or method signatures?
5. How large was the change? (additions/deletions)

**Return ONLY JSON array with ALL PRs scored. Use exact scores (0.87, 0.93, 0.76):**
[
    {{"number": 123, "score": 0.95, "reason": "PR #123 modified {file_path} and removed a null check at line {line_number} in the processPayment() method, directly causing the NullPointerException."}},
    {{"number": 456, "score": 0.78, "reason": "PR #456 refactored the payment processing logic, changing the return type of getPaymentDetails() from Optional to raw type, potentially returning null."}},
    {{"number": 789, "score": 0.45, "reason": "PR #789 updated dependencies, which could have changed the behavior of the PaymentProcessor class."}}
]

Be specific about what changed and why it might cause a NullPointerException. Include the method/function name if possible.
"""'''

content = content.replace(old_prompt, new_prompt)

with open("/app/src/services/github_service.py", "w") as f:
    f.write(content)

print("✅ PR scoring prompt updated with more detailed reasons!")

