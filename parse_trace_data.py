import sys, json, re, heapq


def bulk_copy_bounds_check(start_src, start_dst, consec_count, next_src, next_dst):
	if next_src == start_src + consec_count * 32 and next_dst == start_dst + consec_count * 32:
		if start_src < start_dst:
			if start_src + consec_count * 32 >= start_dst:
				return False
			else:
				return True
		else:
			if start_dst + consec_count * 32 >= start_src:
				return False
			else:
				return True
	else:
		return False

def measure_consecutive_copies(call_copies):
	# quick-n-diry: just track ascending offsets in (start_offset, start_offset + 32, start_offset + 64, ...)
	cur_start = int(call_copies[0]['srcOffset'], 16)
	cur_dst = int(call_copies[0]['dstOffset'], 16)
	cur_consecutive = 1
	max_consecutive = 1

	for copy in call_copies[1:]:
		if bulk_copy_bounds_check(cur_start, cur_dst, cur_consecutive, int(copy['srcOffset'], 16), int(copy['dstOffset'], 16)):
			cur_consecutive += 1
		else:
			max_consecutive = max(cur_consecutive, max_consecutive)
			cur_consecutive = 1
			cur_start = int(copy['srcOffset'], 16)
			cur_dst = int(copy['dstOffset'], 16)

	max_consecutive = max(cur_consecutive, max_consecutive)

	return max_consecutive

# traverse the callgraph removing the cost of calling child contracts from parent gasUsed
# we need the aggregate gas spent in each contract (which doesn't include the cost of subcalls, other than cost of CALL itself)
# ---
# modifies tx_trace in-place
def trim_subcall_costs(tx_trace):
	if not 'gasUsed' in tx_trace:
		return 0

	if not 'calls' in tx_trace:
		# base case
		return int(tx_trace['gasUsed'], 16)
	else:
		call_gas_used = int(tx_trace['gasUsed'], 16)
		original_call_gas_used = call_gas_used

		for subcall in tx_trace['calls']:
			call_gas_used -= trim_subcall_costs(subcall)

		tx_trace['gasUsed'] = hex(call_gas_used)
		return call_gas_used

def aggregate_mcopy_savings(tx_trace):

	# return [{account: (gas_used, gas_used_mcopy, consecutive_copies), ...]
	if not 'gasUsed' in tx_trace:
		return []

	if not 'calls' in tx_trace:
		gas_used = tx_trace['gasUsed']
		gas_used_mcopy = gas_used
		
		copies = tx_trace['memcopyState']['copies']
		if len(copies) > 0:
			gas_used_mcopy = estimate_mcopy_savings(copies)

		return [{'account': tx_trace['to'], 'gas_used': gas_used, 'gas_used_mcopy': gas_used_mcopy, 'copies': copies}]
	else:
		result = []
		for subcall in tx_trace['calls']:
			result += aggregate_mcopy_savings(subcall)

		return result

# return a map of contract_address: (copy count, gas spent), include reverted calls
# TODO figure out how to make the tracer emit gas spent in each call frame (without including internal calls)
def parse_contract_copies(tx_trace):
	trim_subcall_costs(tx_trace)

	# TODO sanity check which sums up call costs and makes sure that they sum up to the original "un-trimmed" trace

	savings = aggregate_mcopy_savings(tx_trace)
	import pdb; pdb.set_trace()

def main():
	trace_file = sys.argv[1]
	trace_lines = None

	max_copy_sizes = {}
	aggregate_copies = {}

	with open(trace_file) as f:
		trace_lines = f.readlines()

	cur_tx = None
	cur_block = None

	i = 0
	tx = None
	while i < len(trace_lines):
		line = trace_lines[i]

		if line.startswith('tx: '):
			tx = line[4:]
			# print(tx)

			if i + 1 >= len(trace_lines):
				break
			elif trace_lines[i + 1] == 'error':
				i += 1
			elif trace_lines[i + 1].startswith("{"):
				trace_result = json.loads(trace_lines[i + 1].replace("'", '"').replace('None', '"None"'))
				copies = parse_contract_copies(trace_result)
				for k, v in zip(copies.keys(), copies.values()):
					if k in max_copy_sizes:
						if v['max_consecutive_copies'] > max_copy_sizes[k]:
							max_copy_sizes[k] = v['max_consecutive_copies']
					else:
						max_copy_sizes[k] = v['max_consecutive_copies']

					if not k in aggregate_copies:
						aggregate_copies[k] = {'copy_count': 0, 'gas_used': 0}

					aggregate_copies[k]['copy_count'] += v['copy_count']
					aggregate_copies[k]['gas_used'] += v['gas_used']

				i += 1

		i += 1

	aggregate_copies = zip(aggregate_copies.keys(), aggregate_copies.values())
	aggregate_copies = list(reversed(sorted(aggregate_copies, key=lambda x: x[1]['copy_count'])))

	max_copy_sizes = zip(max_copy_sizes.keys(), max_copy_sizes.values())
	max_copy_sizes = list(reversed(sorted(max_copy_sizes, key=lambda x: x[1])))

	print("aggregate copy-count/gas-consumed graph csv:")
	print()
	print("contract,total-copy-count,total-gas-used")
	for c in aggregate_copies[:10]:
		print(c[0],c[1]['copy_count'],c[1]['gas_used'])

	print()
	print()
	print("contracts with largest consecutive copy sizes csv:")
	print()
	print("contract,consec-copy-count")
	for c in max_copy_sizes[:10]:
		print(c[0],c[1])

if __name__ == "__main__":
	main()
