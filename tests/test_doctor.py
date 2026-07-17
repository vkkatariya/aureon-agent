from aureon_agent.doctor import check_python

def test_check_python():
    status, details = check_python()
    assert status == "✅" or status == "❌"
    assert "Python" in details
