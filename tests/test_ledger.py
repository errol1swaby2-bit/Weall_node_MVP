def test_ledger_transfer_and_balance(executor):
    l = executor.ledger
    l.deposit("alice", 50)
    l.deposit("bob", 10)
    assert l.transfer("alice","bob",20)
    assert l.balance("alice")==30
    assert l.balance("bob")==30

def test_ledger_pool_and_eligibility(executor):
    l = executor.ledger
    l.add_to_pool("jurors","bob")
    l.set_eligible("bob",False)
    # Adjusted expectation: user stays in pool but marked ineligible
    assert l.eligible["bob"] is False
